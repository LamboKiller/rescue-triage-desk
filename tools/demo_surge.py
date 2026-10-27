"""Synthetic SURGE for the video's catastrophe scene (demo video scene 9). Fictional people, phones 51 9XXXX-0000; own words, not templates.

  python tools/demo_surge.py --url http://127.0.0.1:8095 --n 60 --rate burst            # everything at once -> queue fills ("em fila")
  python tools/demo_surge.py --url ... --n 60 --rate steady --per-sec 4                  # a stream
  python tools/demo_surge.py --url ... --n 60 --rate wave                                # three bursts with pauses
  python tools/demo_surge.py --url ... --n 60 --rate burst --dry-run                     # print the texts, post nothing
  python tools/demo_surge.py --url ... --watch                                           # also poll queue states until done

Mix: ~65 % WhatsApp-style requests, ~20 % 'transcrição de ligação' (call transcript style), the rest relays and a few vague ones.
Streets are REAL flooded streets (data/streets_flood.csv x data/hazards/street_points.csv) inside the flooded 4º Distrito / Navegantes
(Porto Alegre) and Canoas / Mathias Velho boxes, so the pins land on the map where the water was. No model is called by this tool: the desk
(sample or live) processes the queue.
"""
import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOXES = {'Porto Alegre': (-30.043, -29.990, -51.240, -51.185), 'Canoas': (-29.945, -29.890, -51.215, -51.160)}
DAY = '2024-05-06'

OPEN = ['socorro', 'gente pelo amor de deus', 'alguem ajuda', 'urgente', 'boa tarde, preciso de ajuda', 'a agua subiu de novo', 'nao aguento mais', 'oi, to ilhado']
WATER = ['a agua ja bate no peito', 'a agua chegou no segundo degrau da escada', 'agua entrando pela porta', 'a rua virou rio', 'agua na altura da janela',
         'o nivel subiu uns 30 cm na ultima hora', 'ta tudo coberto, so vemos o telhado dos carros', 'a luz acabou e a agua nao para de subir']
WHO = ['somos {n} aqui em casa', 'tem {n} pessoas comigo', 'estamos em {n}', 'a familia toda, {n} pessoas']
EXTRA = ['uma crianca de colo', 'minha mae acamada', 'um senhor de cadeira de rodas', 'uma gestante', 'um idoso que precisa de oxigenio', 'dois cachorros', 'ninguem ferido por enquanto',
         'meu pai com diabetes sem remedio', 'um bebe de 3 meses', '']
PLACE = ['{street} {num}, {city}', 'na {street}, numero {num} ({city})', '{street}, {num}. {city}', 'moro na {street} {num} aqui em {city}']
CLOSE = ['por favor mandem barco', 'preciso de bote', 'estamos no segundo andar', 'estamos no telhado', 'nao da pra sair a pe', 'ja ligamos e nao atendem', 'fone 51 9{p}-0000']
VAGUE = ['tem gente presa perto do mercado la na vila, agua ate o peito, mandem alguem', 'familia ilhada na rua de tras da escola, nao sei o nome da rua',
         'perto da ponte tem uns 5 isolados, ja faz horas']
SERVICES = [
    '[Transcrição de ligação · 193 · FICTÍCIA] Atendente: bombeiros, qual a emergência? Pessoa: a água entrou aqui, {street} {num}, {city}. Atendente: quantas pessoas? Pessoa: {n}, {extra}. Atendente: a água continua subindo? Pessoa: sim, já na cintura.',
    '[Transcrição de ligação · Defesa Civil · FICTÍCIA] Pessoa: moro na {street}, {num}, {city}, estamos {n}, não tem como sair. Atendente: consegue subir para um andar alto? Pessoa: já estamos no telhado, {extra}.',
    '[Transcrição de ligação · 192 · FICTÍCIA] Atendente: SAMU. Pessoa: preciso de ajuda, {extra}, {street} {num}, {city}, a rua está alagada e a ambulância não entra.',
    '[Transcrição de ligação · 190 · FICTÍCIA] Pessoa: tem {n} pessoas presas na {street} {num}, {city}, a água passou da janela do térreo. Atendente: telefone para contato? Pessoa: 51 9{p}-0000.']


def streets():
    flood = {(r['normalized_name'], r['municipality']): r for r in csv.DictReader(open(ROOT/'data'/'streets_flood.csv', encoding='utf-8'))}
    out = {k: [] for k in BOXES}
    for r in csv.DictReader(open(ROOT/'data'/'hazards'/'street_points.csv', encoding='utf-8')):
        city = r['municipality']
        if city not in BOXES or not r['display_name'].startswith(('Rua ', 'Avenida ', 'Travessa ')):
            continue
        s, n, w, e = BOXES[city]
        if not (s < float(r['lat']) < n and w < float(r['lon']) < e):
            continue
        f = flood.get((r['normalized_name'], city))
        if f and f['any_in_water_'+DAY] == '1':
            out[city].append(r['display_name'])
    return out


def build(n, seed):
    rng = random.Random(seed)
    pool = streets()
    texts, relay = [], []
    for i in range(n):
        city = rng.choices(['Porto Alegre', 'Canoas'], [.55, .45])[0]
        street = rng.choice(pool[city])
        num = rng.randint(20, 990)
        people = rng.randint(2, 9)
        extra = rng.choice(EXTRA) or 'todos conscientes'
        phone = f'{rng.randint(1000, 9999)}'
        roll = rng.random()
        if roll < .06:
            text = rng.choice(VAGUE)
        elif roll < .26:
            text = rng.choice(SERVICES).format(street=street, num=num, city=city, n=people, extra=extra, p=phone)
        elif roll < .34 and relay:
            text = 'REPASSANDO do grupo: '+rng.choice(relay)
        else:
            parts = [rng.choice(OPEN), rng.choice(WATER), rng.choice(WHO).format(n=people)]
            e = rng.choice(EXTRA)
            if e:
                parts.append(e)
            parts += [rng.choice(PLACE).format(street=street, num=num, city=city), rng.choice(CLOSE).format(p=phone)]
            text = ', '.join(parts)
            relay.append(text)
        texts.append(text)
    return texts


def post(url, path, body, timeout=60):
    request = urllib.request.Request(url.rstrip('/')+path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b'{}')
        except ValueError:
            return exc.code, {}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--url', default='http://127.0.0.1:8095')
    p.add_argument('--n', type=int, default=60)
    p.add_argument('--rate', choices=['burst', 'steady', 'wave'], default='burst')
    p.add_argument('--per-sec', type=float, default=4.0)
    p.add_argument('--batch', type=int, default=20, help='messages per /api/intake call')
    p.add_argument('--seed', type=int, default=24)
    p.add_argument('--time', default='15:00', help='replay clock HH:MM on 2024-05-06')
    p.add_argument('--tag', default='surge')
    p.add_argument('--watch', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    texts = build(args.n, args.seed)
    if args.dry_run:
        for t in texts:
            print('-', t)
        return
    stamp = f'{DAY}T{args.time}:00-03:00'
    run = int(time.time()) % 100000
    msgs = [{'text': t, 'received_at': stamp, 'message_id': f'{args.tag}-{run}-{i:03d}'} for i, t in enumerate(texts)]
    batches = [msgs[i:i+args.batch] for i in range(0, len(msgs), args.batch)]
    acks = []
    t0 = time.time()
    for k, batch in enumerate(batches):
        status, body = post(args.url, '/api/intake', {'replay_time': stamp, 'messages': batch})
        if status >= 300:
            sys.exit(f'/api/intake {status}: {body}')
        acks += body.get('messages', [])
        print(f'lote {k+1}/{len(batches)}: {len(batch)} enviadas ({status}) +{time.time()-t0:.1f}s')
        if args.rate == 'steady':
            time.sleep(len(batch)/args.per_sec)
        elif args.rate == 'wave' and k < len(batches)-1:
            time.sleep(6)
    print(f'{len(acks)} aceitas em {time.time()-t0:.1f}s')
    if args.watch:
        ids = [a['message_id'] for a in acks]
        deadline = time.time()+600
        while time.time() < deadline:
            states = {}
            for i in ids:
                try:
                    with urllib.request.urlopen(args.url.rstrip('/')+'/api/queue/'+i, timeout=10) as r:
                        s = json.loads(r.read()).get('state', '?')
                except Exception:
                    s = '?'
                states[s] = states.get(s, 0)+1
            print(f'  {time.time()-t0:5.0f}s  {states}')
            if not states.get('queued') and not states.get('running'):
                break
            time.sleep(3)


if __name__ == '__main__':
    main()
