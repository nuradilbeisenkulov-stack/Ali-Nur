"""Small transparent multilingual search lexicon, not a label or priority table.

Category documents and priority conditions always come from taxonomy.json.
These concepts normalize wording in documents and queries to the same vocabulary.
"""
import re
from .language import normalize

# Regexes match full lexical starts (rather than dangerous substring matches).
# Expansions are maintained manually; they are not trained from administrator replies.
LEXICON = {
    'insult': r'оскорб\w*|токсич\w*|обзыв\w*|обозв\w*|матер\w*|insult\w*|abusi\w*|haqorat\w*|балағат\w*|қорла\w*|insultó|insulta\w*|ofens\w*|xing\w*',
    'racism': r'расис\w*|расиз\w*|ксенофоб\w*|racis\w*',
    'family': r'семь\w*|родн\w*|родствен\w*|family|familia|família|отбас\w*|oila\w*',
    'cheat': r'чит(?:ы|ер\w*|а|ами|ов|ить)?|аимбот\w*|aimbot\w*|cheat\w*|софт\w*|сторонн\w*\s+по|speedhack\w*|wallhack\w*|читтер\w*',
    'flying': r'лета\w*|летит|flying|ұшып|uchib',
    'dm': r'дм\w*|dm|deathmatch\w*|уби\w*|убь\w*|урон\w*|убил\w*|стреля\w*|kill\w*|shoot\w*|өлтір\w*|otib|o[\x27’]ldir\w*|mató|matar\w*|matou',
    'rp': r'рп|rp|roleplay|отыгр\w*',
    'green': r'gz|зз|зел[её]н\w*|green\s+zone|жасыл\s+аймақ',
    'scam': r'обман\w*|мошенн\w*|вымога\w*|scam\w*|fraud\w*|алда\w*|aldadi\w*|firibgar\w*|estafa\w*|golpe\w*',
    'property': r'имуществ\w*|машин\w*|автомобил\w*|бизнес\w*|квартир\w*|house|car|vehicle|property|көлік\w*|мүлік\w*|mashina\w*|coche|carro',
    'rmt': r'rmt|реальн\w*\s+день\w*|за\s+реал\w*|real\s+money',
    'advert': r'реклам\w*|advert\w*|прода[её]т\s+аккаунт\w*|sell\w*\s+account\w*',
    'admin': r'админ\w*|администрат\w*|admin\w*|модератор\w*|moderator\w*',
    'complaint': r'жалоб\w*|жб|complaint\w*|шағым\w*|shikoyat\w*|queja\w*|reclamação',
    'question': r'вопрос\w*|как|где|почему|сколько|зачем|механик\w*|лицензи\w*|how|where|question\w*|қалай|қайда|сұрақ\w*|qanday|qayer\w*|savol\w*|cómo|dónde|como|onde',
    'help': r'помо\w*|помощ\w*|help\w*|көмек\w*|yordam\w*|ayuda\w*|ajuda\w*',
    'stuck': r'застр\w*|текстур\w*|телепорт\w*|баг\w*|stuck|bug\w*|teleport\w*|тұрып\s+қал\w*|кептел\w*|qotib|atascado|preso',
    'account': r'аккаунт\w*|акк|account\w*|тіркелгі\w*|akkaunt\w*|cuenta|conta',
    'hacked': r'взлом\w*|украл\w*|украд\w*|украли|hack\w*|stolen|бұз\w*|ұрла\w*|buzib|o[\x27’]g[\x27’]ir\w*|hackea\w*|invadi\w*',
    'access_lost': r'потер\w*\s+доступ\w*|нет\s+доступ\w*|не\s+(?:могу\s+)?(?:войти|зайти)|lost\s+access|can\x27t\s+log\s*in|cannot\s+log\s*in|no\s+puedo\s+(?:entrar|acceder)|não\s+consigo\s+entrar|кіре\s+алмай\w*|kira\s+olmay\w*',
    'missing': r'пропа\w*|потер\w*|исчез\w*|missing|lost|жоғал\w*|yo[\x27’]qol\w*|perdid\w*|desapare\w*',
    'payment': r'плат[её]ж\w*|оплат\w*|донат\w*|платил\w*|пополн\w*|payment\w*|paid|pago\w*|pagu\w*|pagamento\w*|төл[еғ]\w*|донат\w*|to[\x27’]lo\w*',
    'refund': r'возврат\w*|верни\w*\s+день\w*|верну\w*\s+день\w*|refund\w*|ақшамды\s+қайтар\w*|pulimni\s+qaytar\w*|reembolso\w*|devolu\w*',
    'appeal': r'апелл\w*|обжал\w*|разбан\w*|размут\w*|сними\w*\s+(?:бан|блок\w*)|снять\s+(?:бан|блок\w*)|unban\w*|unblock\w*|appeal\w*|блоктан\s+шығар\w*|баннан\s+шығар\w*|ban(?:ni)?\s+(?:olib|och\w*)|apela\w*|desbloqu\w*',
    'ban': r'бан|бана|баном|банят|забан\w*|блокиров\w*|banned|ban|baneo|bloque\w*',
    'punish': r'накаж\w*|наказ\w*|забаньте|забань\w*|ban\s+(?:him|her|them|player)|punish\w*|жазала\w*|jazola\w*|castig\w*|punir\w*',
    'mass': r'массов\w*|у\s+всех|весь\s+сервер|all\s+players|everyone|барлы\w*|hammada',
    'threat': r'угро\w*|найду\s+(?:тебя|адрес)|threat\w*|қорқыт\w*|tahdid\w*|amenaz\w*|ameaç\w*',
    'outside': r'вне\s+игры|реальн\w*\s+жизн\w*|реале|real\s+life|outside\s+(?:the\s+)?game|өмірде',
    'evidence': r'доказатель\w*|скрин\w*|видео\w*|evidence|screenshot\w*|дәлел\w*|dalil\w*|captura\w*',
    'offtopic': r'офф?топ\w*|пуст\w*|привет|ау|hello|hi|сәлем|salom|hola|olá',
    'rules': r'правил\w*|rule\w*|ереже\w*|qoida\w*|regla\w*',
    'suggestion': r'предложен\w*|suggestion\w*|ұсыныс\w*',
}
PATTERNS = {name: re.compile(r'(?<!\w)(?:' + pattern + r')(?!\w)', re.I) for name, pattern in LEXICON.items()}
STOP = set('и в во на за от до по не ни но я он она они вы мы это как что у с со к ко о об а для из же the a an is was of to me my your for this that at it иго его меня тебе ты там есть'.split())


def concepts(text: str) -> set[str]:
    text = normalize(text)
    return {name for name, pattern in PATTERNS.items() if pattern.search(text)}


def tokens(text: str) -> set[str]:
    words = re.findall(r'[^\W\d_]+', normalize(text))
    result = set()
    for word in words:
        if len(word) < 3 or word in STOP:
            continue
        # A deliberately simple prefix stemmer; confidence is not calibrated.
        result.add(word[:6] if len(word) > 6 else word)
    return result


def features(text: str) -> set[str]:
    return tokens(text) | {'@' + c for c in concepts(text)}
