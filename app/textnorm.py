"""ACC1: conservative slang/typo normalisation for the deterministic layer (accent-free, lower-case in, lower-case out)."""
import re

WORDS = {'vc': 'voce', 'vcs': 'voces', 'tbm': 'tambem', 'tb': 'tambem', 'nois': 'nos', 'aki': 'aqui', 'aqi': 'aqui', 'agr': 'agora',
         'pq': 'porque', 'somo': 'somos', 'entro': 'entrou', 'crinca': 'crianca', 'crincas': 'criancas', 'cranca': 'crianca',
         'barko': 'barco', 'agu': 'agua', 'socoro': 'socorro', 'sucorro': 'socorro', 'resgste': 'resgate', 'rezgate': 'resgate',
         'rescate': 'resgate', 'telhdo': 'telhado', 'telado': 'telhado', 'poa': 'porto alegre', 'nh': 'novo hamburgo',
         'sl': 'sao leopoldo'}
REPEAT = re.compile(r'([a-z])\1{2,}')
PLACE_WORDS = {'niteroy': 'niteroi', 'mathias': 'matias'}


def place_word(word):
    """Conservative spelling variants; catalogue and source text use the same key."""
    return PLACE_WORDS.get(word, 'rua' if re.fullmatch(r'ru+a+', word) else word)
STRETCHED = re.compile(r'\b(rua|agua|casa|ajuda|socorro|barco)[aeiou]+\b')


def slang(plain):
    """Normalise an already accent-folded, lower-case text: shouting letters, stretched endings, common abbreviations/typos."""
    text = REPEAT.sub(r'\1', plain)
    text = STRETCHED.sub(lambda m: m[1], text)
    return re.sub(r'\b[a-z]{2,8}\b', lambda m: WORDS.get(m[0], m[0]), text)
