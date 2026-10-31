"""Deterministic, offline triage. No training labels or administrator text are read."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from threading import RLock

from .config import get_data_dir
from .language import normalize, detect_language, reply, contextual_review_reply
from .models import TicketIn
from .llm import LocalModel
from .semantics import concepts, tokens


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TriageEngine:
    def __init__(self, data_dir: Path | str | None = None):
        self.data_dir = Path(data_dir) if data_dir else get_data_dir()
        try:
            self.taxonomy = json.loads((self.data_dir / 'taxonomy.json').read_text(encoding='utf-8'))
            source = json.loads((self.data_dir / 'rules.json').read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise RuntimeError('Case files not found. Set SUPPORT_DATA_DIR to the folder containing taxonomy.json and rules.json.') from exc
        self.categories = self.taxonomy['categories']
        self.priorities = self.taxonomy['priorities']
        if not self.categories or not self.priorities:
            raise ValueError('Taxonomy must contain categories and priorities')
        if any(p['code'] not in {'p0', 'p1', 'p2', 'p3'} for p in self.priorities):
            raise ValueError('Taxonomy priority does not match the API contract')
        if len({c['code'] for c in self.categories}) != len(self.categories):
            raise ValueError('Taxonomy category codes must be unique')
        self._category_docs = []
        for category in self.categories:
            title = category.get('title', '')
            examples = category.get('examples', [])
            self._category_docs.append((category, concepts(title), concepts(' '.join(examples)), tokens(title + ' ' + ' '.join(examples)), [normalize(e) for e in examples]))
        self.rules = []
        self._rule_docs = []
        for section in source.get('rules', []):
            for point in section.get('points', []):
                if not point.get('ref') or not point.get('text'):
                    continue
                item = {'ref': str(point['ref']), 'text': point['text'], 'section': section['category']}
                self.rules.append(item)
                # Sanctions are not relevant evidence for finding the alleged behavior.
                semantic_text = point['text'].split('|')[0]
                self._rule_docs.append((item, concepts(semantic_text), tokens(semantic_text), semantic_text))
        self._citation_set = {(r['section'], r['ref'], r['text']) for r in self.rules}
        # Rare textual terms carry more weight than common regulatory language.
        self._idf = {}
        for _, _, terms, _ in self._rule_docs:
            for term in terms:
                self._idf[term] = self._idf.get(term, 0) + 1
        self._idf = {t: math.log(1 + len(self.rules) / count) for t, count in self._idf.items()}
        self._lock = RLock()
        # At most 5,000 minimal fingerprints; no raw ticket bodies or cross-dataset identity graph.
        self._seen = OrderedDict()
        self._serial = 0
        self.ai = LocalModel()

    def reset_dedup(self):
        with self._lock:
            self._seen.clear()

    def _classify(self, kind: str, text: str):
        query_concepts, query_tokens = concepts(text), tokens(text)
        ranked = []
        for category, title_concepts, example_concepts, doc_tokens, examples in self._category_docs:
            if category['kind'] != kind:
                continue
            title_hits = query_concepts & title_concepts
            example_hits = query_concepts & example_concepts
            score = sum(1.2 if c in {'question', 'help', 'property', 'account', 'complaint'} else 3.0 for c in title_hits)
            score += sum(0.5 if c in {'question', 'help', 'property', 'account', 'complaint'} else 1.4 for c in example_hits - title_hits)
            score += min(2.5, 0.55 * len(query_tokens & doc_tokens))
            if normalize(text).strip(' .!?') in [e.strip(' .!?') for e in examples]:
                score += 4.0
            # The title is the category definition; generic words alone carry little certainty.
            ranked.append((score, category))
        if not ranked:
            raise ValueError('kind is not defined in taxonomy.json')
        ranked.sort(key=lambda item: item[0], reverse=True)
        best, category = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0
        if best < 0.8:
            # A taxonomy-provided catch-all, chosen by its description, never a new label.
            fallback = [c for _, c in ranked if re.search(r'друг|офф?топ|пуст', normalize(c.get('title', '')))]
            category = fallback[0] if fallback else ranked[-1][1]
            confidence = 0.25
        else:
            confidence = min(0.92, 0.44 + min(best, 7) * 0.055 + min(max(best-second, 0), 4) * 0.045)
            if best - second < 0.6:
                confidence = min(confidence, 0.59)
        if len(query_tokens) < 2:
            confidence = min(confidence, 0.58)
        return category, confidence, query_concepts

    def _priority(self, query: set, kind: str, category: dict, evidence: bool):
        # Conditions are read from taxonomy; semantic matching only interprets its words.
        complaint = kind == 'complaint' or 'complaint' in concepts(category.get('title', ''))
        for priority in sorted(self.priorities, key=lambda p: p['code']):
            for clause in priority.get('rule', '').split(','):
                c = concepts(clause)
                if not c:
                    continue
                if 'evidence' in c:
                    needed = not bool(re.search(r'\bбез\b', normalize(clause)))
                    matches = complaint and evidence == needed
                elif 'hacked' in c or 'access_lost' in c:
                    matches = bool(query & {'hacked', 'access_lost'})
                elif 'mass' in c:
                    matches = {'mass', 'stuck'} <= query
                elif 'threat' in c:
                    matches = 'threat' in query and ('outside' not in c or 'outside' in query)
                elif 'scam' in c and 'property' in c:
                    matches = {'scam', 'property'} <= query
                elif 'advert' in c or 'rmt' in c:
                    matches = bool(query & {'advert', 'rmt'})
                elif 'question' in c and 'rules' in c:
                    matches = {'question', 'rules'} <= query
                else:
                    matches = bool((c - {'complaint', 'evidence', 'property', 'account'}) & query)
                if matches:
                    return priority['code'], priority.get('rule', '')
        return sorted(self.priorities, key=lambda p: p['code'])[-1]['code'], None

    def _retrieve(self, text: str, raw_hint, category: dict):
        q_concepts, q_tokens = concepts(text), tokens(text)
        # Use the player's text; aliases/refs alone cannot establish relevance.
        raw = ' '.join(raw_hint) if isinstance(raw_hint, list) else str(raw_hint or '')
        hint_refs = set(re.findall(r'\b\d+(?:\.\d+)+\b', raw))
        hint_refs |= {str(x) for x in category.get('rules', [])}
        scored = []
        behavior = {'insult', 'racism', 'cheat', 'dm', 'scam', 'rmt', 'advert', 'threat'}
        for item, doc_concepts, doc_tokens, semantic_text in self._rule_docs:
            section = normalize(item['section'])
            overlap = q_tokens & doc_tokens
            topical = q_concepts & doc_concepts & behavior
            eligible = False
            # Scope is checked against the real source section and point text, not ref numbers.
            if 'общие правила' in section:
                eligible = bool(topical)
                if 'green' in doc_concepts and 'green' not in q_concepts:
                    eligible = False
                if 'property' in doc_concepts and 'dm' in topical and not (q_concepts & {'property'}):
                    eligible = False
            elif 'зелен' in section:
                eligible = 'green' in q_concepts and bool(topical & {'dm', 'scam'})
            elif 'жалоб' in section:
                # Cite procedure only for explicit procedural questions, not arbitrary complaints.
                eligible = {'question', 'complaint'} <= q_concepts and len(overlap) >= 2
            else:
                # Specialized rule books need an explicit scoped context (e.g. family event).
                scope = tokens(item['section']) - {'правил', 'органи', 'нахожд', 'общие'}
                eligible = bool(topical) and bool(q_tokens & scope) and len(overlap) >= 2
            # Specific contexts in a rule cannot be inferred from generic abuse/DM.
            lead = normalize(semantic_text.split('.')[0])
            for qualifier in ('никнейм', 'стрим', 'медийн', 'религи', 'политик', 'фашиз', 'нациз', 'удален'):
                if qualifier in lead and qualifier not in normalize(text):
                    eligible = False
            if not eligible:
                continue
            # Avoid rules whose only overlap is common abuse/violation wording.
            meaningful_overlap = overlap - {'игрок', 'игрока', 'правил', 'наруше', 'запрещ', 'случае', 'любой', 'любыми'}
            if not topical and len(meaningful_overlap) < 2:
                continue
            score = sum(self._idf.get(t, 0) for t in meaningful_overlap) + 3 * len(topical)
            # Context in the source point that was not asserted lowers relevance.
            unasserted = (doc_concepts & behavior) - q_concepts
            score -= 1.5 * len(unasserted)
            if item['ref'] in hint_refs:
                score += 0.35
            if score >= 4.2 or (len(topical) == 1 and len(meaningful_overlap) >= 1):
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return []
        # A single best point keeps the MVP conservative and avoids section-number ambiguity.
        best_score, best = scored[0]
        if len(scored) > 1 and best_score - scored[1][0] < 0.45 and best['section'] != scored[1][1]['section']:
            return []
        if (best['section'], best['ref'], best['text']) not in self._citation_set:
            return []
        return [dict(best)]

    def _duplicate(self, ticket: dict, text: str) -> bool:
        reporter, created = ticket.get('reporter_hash'), ticket.get('created_at')
        if not reporter or not created or len(text.strip()) < 12 or len(tokens(text)) < 2:
            return False
        try:
            date = datetime.fromisoformat(created.replace('Z', '+00:00'))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            timestamp = date.timestamp()
        except (ValueError, TypeError, OverflowError):
            return False
        key = digest(str(reporter) + ':' + ticket['kind'])
        text_hash = digest(normalize(text).strip())
        terms = frozenset(digest(t)[:16] for t in tokens(text))
        target = digest(str(ticket.get('reported_hash') or ticket.get('reported_nick') or ''))
        ticket_id = digest(ticket['ticket_id']) if ticket.get('ticket_id') else None
        duplicate = False
        with self._lock:
            for prior_key, record in reversed(self._seen.items()):
                old_identity, old_time, old_text, old_terms, old_target, old_id = record
                if old_identity != key or abs(timestamp - old_time) > 3600 or old_target != target:
                    continue
                if ticket_id and old_id == ticket_id:
                    # Re-evaluating the same ID is not a different ticket.
                    continue
                similarity = len(terms & old_terms) / max(1, len(terms | old_terms))
                if text_hash == old_text or (len(terms & old_terms) >= 4 and similarity >= 0.82):
                    duplicate = True
                    break
            # Out-of-order timestamps are supported within this bounded ingestion window.
            self._serial += 1
            self._seen[self._serial] = (key, timestamp, text_hash, terms, target, ticket_id)
            if len(self._seen) > 5000:
                self._seen.popitem(last=False)
        return duplicate

    def triage(self, ticket: dict, *, synthetic: bool = False) -> dict:
        ticket = TicketIn.model_validate(ticket).model_dump()
        # Explicit allowlist: no admin/system/tool text and no outcome metadata.
        source_messages = [m for m in ticket['messages'] if m['role'] in {'player', 'user', 'reporter', 'reported_player'}]
        player_messages = [m for m in source_messages if m['role'] != 'reported_player']
        text = '\n'.join(m['text'] for m in player_messages)
        normalized = normalize(text)
        lang, lang_confidence, lang_reason = detect_language(text, ticket.get('lang'))
        category, confidence, query = self._classify(ticket['kind'], text)
        evidence_metadata = ticket.get('images_count') is not None or any(m.get('attachments') is not None for m in source_messages)
        evidence = (ticket.get('images_count') or 0) > 0
        for message in source_messages:
            attachments = message.get('attachments')
            if isinstance(attachments, int):
                evidence |= attachments > 0
            elif isinstance(attachments, (list, dict)):
                evidence |= len(attachments) > 0
        reasons = ['Категория определена локальной эвристикой по taxonomy.json; confidence не является калиброванной вероятностью.']
        if ticket['kind'] == 'complaint' or 'reported_player' in {m['role'] for m in source_messages}:
            reasons.append('Тексты заявителя и обвиняемого — заявления сторон, а не установленные факты.')
        if evidence:
            reasons.append('Вложения указаны только в метаданных. Их содержимое не анализировалось и не подтверждает нарушение.')
        elif not evidence_metadata:
            reasons.append('Метаданных о вложениях нет; наличие доказательств неизвестно.')
        if lang_reason:
            reasons.append(lang_reason)
        confidence = round(min(confidence, lang_confidence), 3)
        priority, matched_rule = self._priority(query, ticket['kind'], category, evidence)
        if matched_rule:
            reasons.append('Приоритет по критерию taxonomy.json: ' + matched_rule)
        else:
            confidence = min(confidence, 0.49)
            reasons.append('Критерий приоритета не распознан; выбран минимальный приоритет из taxonomy.json, нужна проверка.')
        citations = self._retrieve(text, ticket.get('rule_refs_raw'), category)
        if citations:
            reasons.append('Найден пункт с совпадением темы и проверенным источником; применимость и факты проверяет администратор.')
        else:
            reasons.append('Подтверждённый релевантный пункт не найден: правила в черновике не цитируются. Указанный игроком номер сам по себе не является основанием.')
        nickname = ticket.get('reported_nick')
        if not nickname:
            match = re.search(r'(?<!\w)([A-Za-z][A-Za-z0-9]{1,24}_[A-Za-z][A-Za-z0-9]{1,24})(?!\w)', text)
            nickname = match.group(1) if match else None
        # Region and server language never become a server identifier.
        server_match = re.search(r'\b(?:сервер(?:е|а)?|server|сервері)\s*(?:№|#|номер)?\s*(\d{1,3})\b', normalized)
        server = server_match.group(1) if server_match else None
        duplicate = self._duplicate(ticket, text)
        spam = bool(re.search(r'(.)\1{29,}', normalized))
        if duplicate:
            reasons.append('Вероятный дубль: тот же заявитель и адресат, похожий текст, интервал не более часа. Требуется ручная проверка.')
        if spam:
            reasons.append('Вероятный спам: длинная последовательность повторяющихся символов; нужна проверка.')
        needs_human = category['code'] in self.taxonomy.get('needs_human_always', [])
        if query & {'payment', 'refund', 'hacked', 'access_lost', 'appeal', 'ban'}:
            needs_human = True
            reasons.append('Платёж, возврат, безопасность аккаунта или блокировка требуют решения человека.')
        if 'admin' in query and (ticket['kind'] == 'complaint' or query & {'complaint', 'punish', 'insult', 'ban'}):
            needs_human = True
            reasons.append('Жалоба на администратора требует отдельного рассмотрения человеком.')
        if ticket['kind'] == 'complaint' or query & {'punish', 'dm', 'insult', 'cheat', 'scam', 'rmt', 'advert', 'racism', 'threat'}:
            needs_human = True
            reasons.append('Жалоба или возможное наказание другого игрока: окончательное решение принимает человек.')
        if confidence < 0.7 or lang in {'lat', 'und'} or duplicate or spam or not text.strip():
            needs_human = True
            reasons.append('Недостаточно уверенности или контекста: администратор должен проверить категорию и черновик.')
        if category['code'] in self.taxonomy.get('needs_human_always', []):
            reasons.append('Эта категория всегда требует человека согласно taxonomy.json.')
        draft = reply(lang, bool(evidence))
        if lang == 'ru':
            draft['text'] = contextual_review_reply(lang, category['code'])
        draft['cited'] = citations
        result = {
            'lang': lang, 'category': category['code'], 'priority': priority,
            'is_spam_or_duplicate': bool(duplicate or spam),
            'extracted': {'nickname': nickname, 'rule_refs': list(dict.fromkeys(c['ref'] for c in citations)), 'has_evidence': bool(evidence), 'server': server},
            'draft_reply': draft, 'needs_human': needs_human,
            'confidence': confidence, 'reasons': reasons,
        }
        generated, ai_reason = self.ai.analyze(ticket, result, self.taxonomy, synthetic=synthetic)
        result['reasons'].append(ai_reason)
        if generated:
            result['draft_reply']['text'] = generated['draft_text']
            selected = next(c for c in self.categories if c['code'] == generated['category'])
            result['category'] = selected['code']
            # AI may add escalation, but can never remove safety decisions.
            result['needs_human'] |= generated['needs_human'] or selected['code'] in self.taxonomy.get('needs_human_always', [])
            result['priority'], _ = self._priority(query, ticket['kind'], selected, bool(evidence))
            result['confidence'] = min(result['confidence'], 0.8)
        elif self.ai.enabled:
            result['needs_human'] = True
        if lang in {'kk', 'uz'} and (self.ai.backend != 'gemini' or not generated):
            result['draft_reply']['text'] = contextual_review_reply(lang, result['category'])
            result['reasons'] = [r for r in result['reasons'] if not r.startswith('Контекстный черновик')]
            result['reasons'].append('Для kk/uz свободная генерация компактной модели ненадёжна: использован короткий шаблон по теме обращения. Язык и формулировку должен проверить администратор.')
            result['needs_human'] = True
        return result
