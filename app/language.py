"""Conservative local language hints and neutral reply templates.

These are transparent heuristics, not a statistical language detector. The case
file's lang value is itself heuristic. Explicit ``lat``/``und`` are kept so that
an administrator can resolve them instead of receiving an invented translation.
No source text is changed in place and no external service is called.
"""
from __future__ import annotations

import re
import unicodedata

SUPPORTED = frozenset({"ru", "kk", "uz", "en", "es", "pt", "lat", "und"})
_KNOWN = SUPPORTED - {"lat", "und"}
_SWAPS = str.maketrans({
    "ќ": "қ", "ґ": "ғ", "ѕ": "ң", "є": "ә", "ј": "ө", "ў": "ұ", "ї": "ү",
    "’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'", "´": "'",
})
_WORDS = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)


def normalize(text: str) -> str:
    """Normalize a separate search copy; callers retain the original payload."""
    return unicodedata.normalize("NFKC", text or "").casefold().translate(_SWAPS)


# Distinct lexical cues avoid guessing a language from one shared Latin word,
# a nickname, a rule number, or the name of the game. No training tickets used.
_CUES = {
    "ru": set("я мне меня мой моя мои как где что почему пожалуйста помогите помощь помоги помогите застрял застряла персонаж игрок игрока игроки аккаунт взломали не могу войти оплатил оплатила деньги платёж платеж донат оскорбил оскорбляет украли забанили сервере машине машину есть нужно получил получить лицензию жалоба правила снимать блокировку снять снять запрет администратор админ без причины убил убили в на для он она но это было хочет вернуть".split()),
    "kk": set("маған мен менің маған біз сіз сіздің қалай қайда неге көмек көмектесіңіз көмектесіңізші керек кейіпкерім ойыншы ойыншыны тіркелгі тіркелгім аккаунтым ақшам ақша төлездім төледім түспеді келмеді қалды тұр тұрып кептеліп кептелді бұзылды бұзды ұрлады кіру кіре алмаймын алмай отырмын өтінемін шағым қақпа алдында қайтар сұраймын және үшін жоқ бар".split()),
    "uz": set("men menga mening siz sizning yordam bering iltimos qanday qayerda nima nega akkaunt akkauntim qahramonim o'yinchi o'yin pul pulim to'lov to'ladim kelmadi tushmadi kira olmayapman olmayapti buzib buzilgan qotib qoldim qoldi shikoyat qaytarib kerak bor yo'q va uchun bilan garajdan chiqa".split()),
    "en": set("i me my we our your you please help character player account hacked stolen stuck lost paid payment refund where how why can't cannot login log get need didn't not won't received the was is have has in on with for from this that someone insulted killed garage buy money".split()),
    "es": set("yo mi mis me por favor ayuda ayudar personaje jugador cuenta hackeada robada atascado perdido pagué pago reembolso dónde cómo porqué puedo entrar tengo necesito recibido dinero alguien insultó mató garaje comprar licencia está estoy una el los las para que no".split()),
    "pt": set("eu meu minha meus minhas por favor ajuda ajudar personagem jogador conta invadida roubada preso perdi paguei pagamento reembolso onde como consigo entrar tenho preciso recebido dinheiro alguém insultou matou garagem comprar licença está estou uma os as para que não".split()),
}
_EXCLUSIVE = {
    lang: words - set().union(*(other for other_lang, other in _CUES.items() if other_lang != lang))
    for lang, words in _CUES.items()
}


def _text_hint(text: str) -> tuple[str | None, float]:
    words = set(_WORDS.findall(normalize(text)))
    scores = {lang: len(words & cues) for lang, cues in _CUES.items()}
    eligible = []
    for lang, score in scores.items():
        distinct = len(words & _EXCLUSIVE[lang])
        if score >= 2 and distinct >= 1:
            eligible.append((score, distinct, lang))
    if not eligible:
        return None, 0.0
    eligible.sort(reverse=True)
    best, distinct, lang = eligible[0]
    runner = eligible[1][0] if len(eligible) > 1 else 0
    # Spanish and Portuguese share many words. A tie or nearly equal evidence
    # deliberately remains unresolved unless distinctive cues clearly dominate.
    if runner and (best == runner or (best - runner == 1 and distinct < 2)):
        return None, 0.0
    confidence = min(0.94, 0.66 + 0.045 * best + 0.025 * distinct)
    return lang, round(confidence, 2)


def detect_language(text: str, declared: str | None = None) -> tuple[str, float, str | None]:
    """Return language, heuristic confidence and an optional Russian review note.

    Known declared languages are useful hints, not ground truth. Strong
    disagreement with at least four distinct lexical matches selects the text
    language at deliberately low confidence and requires administrator review.
    """
    declared = normalize(declared).strip() if isinstance(declared, str) else None
    if declared == "lat":
        return "lat", 0.25, "В данных указан lat: язык латинского текста не определён; администратор должен уточнить язык и проверить черновик."
    if declared == "und":
        return "und", 0.2, "В данных указан und: язык неизвестен; перед отправкой требуется уточнение языка и проверка черновика."

    detected, confidence = _text_hint(text)
    if declared in _KNOWN:
        if detected == declared:
            return declared, max(0.86, confidence), None
        if detected is not None and confidence >= 0.88:
            return detected, 0.55, "Язык текста противоречит полю lang; выбран язык по тексту, администратор должен проверить язык и черновик."
        if detected is not None:
            return declared, 0.58, "Поле lang и языковые признаки текста расходятся; администратор должен проверить язык и черновик."
        return declared, 0.72, "Язык взят из поля lang; короткого или неоднозначного текста недостаточно для независимой проверки перевода."
    if detected is not None:
        note = None if confidence >= 0.8 else "Язык определён по ограниченным языковым признакам; администратор должен проверить черновик."
        if declared:
            note = "Значение lang не поддерживается; язык определён по тексту и требует проверки администратором."
            confidence = min(confidence, 0.6)
        return detected, confidence, note
    return "und", 0.2, "Язык не определён: одного слова или латинского написания недостаточно; администратор должен уточнить язык и подготовить черновик."


_TEMPLATES = {
    "ru": (
        "Обращение получено и передано администратору на рассмотрение. После проверки вам сообщат о результате.",
        "Наличие вложений отмечено, их содержание ещё не проверено.",
    ),
    "kk": (
        "Өтінішіңіз қабылданып, әкімшіге қарауға жіберілді. Тексеруден кейін жауап беріледі.",
        "Тіркемелер көрсетілген, бірақ мазмұны әлі тексерілген жоқ.",
    ),
    "uz": (
        "Murojaatingiz qabul qilindi va ko‘rib chiqish uchun administratorga yuborildi. Tekshiruvdan keyin javob beriladi.",
        "Ilovalar ko‘rsatilgan, ammo ularning mazmuni hali tekshirilmagan.",
    ),
    "en": (
        "Your request has been received and passed to an administrator for review. You will receive a reply after the review.",
        "Attachments are listed, but their contents have not yet been checked.",
    ),
    "es": (
        "Hemos recibido tu solicitud y la hemos remitido a un administrador para su revisión. Te responderemos después de revisarla.",
        "Se han indicado archivos adjuntos, pero su contenido aún no se ha revisado.",
    ),
    "pt": (
        "Recebemos sua solicitação e a encaminhamos para análise de um administrador. Você receberá uma resposta após a análise.",
        "Há anexos indicados, mas seu conteúdo ainda não foi verificado.",
    ),
}


def reply(lang: str, has_evidence: bool) -> dict:
    """Make a neutral draft; rule retrieval attaches independently verified cites."""
    if lang not in _TEMPLATES:
        return {
            "lang": "und",
            "text": "Служебный черновик: уточните язык игрока и подготовьте ответ перед отправкой. Обращение ожидает рассмотрения администратора.",
            "cited": [],
        }
    base, evidence_note = _TEMPLATES[lang]
    return {"lang": lang, "text": base + (" " + evidence_note if has_evidence else ""), "cited": []}


def contextual_review_reply(lang: str, category: str) -> str:
    """Conservative topic-specific kk/uz wording when free generation is unreliable."""
    topic = category.rsplit('.', 1)[-1]
    if lang == 'ru':
        subjects = {'help':'трудности с перемещением персонажа', 'payment':'проблему с платежом', 'account':'проблему с аккаунтом', 'insult':'оскорбления в игре', 'dm':'нападение на персонажа', 'cheat':'возможное использование читов', 'scam':'возможный обман', 'admin':'действия администратора', 'question':'вопрос по игре'}
        return 'Вы сообщили про ' + subjects.get(topic, 'ситуацию в игре') + '. Обращение передано администратору на рассмотрение. После проверки вам сообщат о результате.'
    kk = {
        'help': 'Кейіпкеріңіздің қозғала алмай тұрғаны туралы өтінішіңіз қабылданды. Қай жерде тұрғаныңызды және сервер нөмірін жазыңыз.',
        'payment': 'Төлемге қатысты өтінішіңіз қабылданды. Төлем жасалған уақытты нақтылаңыз.',
        'account': 'Аккаунтыңызға қатысты мәселе туралы өтінішіңіз қабылданды. Мәселе қашан басталғанын жазыңыз.',
        'insult': 'Сіз хабарлаған балағаттау туралы шағым қабылданды. Оқиғаның уақытын және сервер нөмірін нақтылаңыз.',
        'dm': 'Кейіпкеріңізге шабуыл жасалғаны туралы шағым қабылданды. Оқиғаның орны мен уақытын нақтылаңыз.',
        'question': 'Ойынға қатысты сұрағыңыз қабылданды. Қай әрекетті орындамақ болғаныңызды нақтылаңыз.',
    }
    uz = {
        'help': 'Qahramoningiz harakatlana olmayotgani haqidagi murojaatingiz qabul qilindi. Joylashuvingiz va server raqamini yozing.',
        'payment': 'To‘lov bo‘yicha murojaatingiz qabul qilindi. To‘lov qilingan vaqtni aniqlashtiring.',
        'account': 'Akkauntingiz bilan bog‘liq muammo haqidagi murojaatingiz qabul qilindi. Muammo qachon boshlanganini yozing.',
        'insult': 'Siz xabar bergan haqorat haqidagi shikoyat qabul qilindi. Voqea vaqti va server raqamini aniqlashtiring.',
        'dm': 'Qahramoningizga hujum qilingani haqidagi shikoyat qabul qilindi. Voqea joyi va vaqtini aniqlashtiring.',
        'question': 'O‘yin haqidagi savolingiz qabul qilindi. Qaysi amalni bajarmoqchi bo‘lganingizni aniqlashtiring.',
    }
    if lang == 'kk':
        return kk.get(topic, 'Сіз хабарлаған жағдай туралы өтініш қабылданды.') + ' Өтініш әкімшіге қарауға жіберілді.'
    return uz.get(topic, 'Siz xabar bergan holat haqidagi murojaat qabul qilindi.') + ' Murojaat ko‘rib chiqish uchun administratorga yuborildi.'


def tokenize(text: str) -> set[str]:
    """Small search tokenizer, with conservative Cyrillic prefix stemming.

    This helper is intentionally approximate and is not a language model.
    """
    stop = set("и в во на за от до по не ни но я он она они вы мы это как что у с со к ко о об а для из же the a an is was of to me my your for this that at it".split())
    return {
        word[:6] if re.search(r"[а-яё]", word) and len(word) > 6 else word
        for word in _WORDS.findall(normalize(text))
        if len(word) >= 3 and word not in stop
    }
