"""Real local inference benchmark on explicitly synthetic multilingual inputs."""
import json
from pathlib import Path
from time import perf_counter
from app.engine import TriageEngine
from scripts.evaluate import percentile

CASES = [
 ('ru','complaint','Игрок Demo_Player оскорбляет меня в общем чате у гаража. Прошу рассмотреть жалобу.'),
 ('ru','report','Я оплатил набор монет, но на баланс ничего не поступило. Что нужно для проверки?'),
 ('kk','report','Көмектесіңізші, кейіпкерім гаражда тұрып қалды, сыртқа шыға алмаймын.'),
 ('uz','report','Yordam bering, qahramonim garajdan chiqa olmayapti.'),
 ('en','report','My account was hacked and I cannot log in. Please help me recover access.'),
 ('es','report','He pagado monedas pero no aparecen en mi cuenta. ¿Pueden revisar el pago?'),
 ('pt','report','Meu personagem está preso na garagem. Preciso de ajuda para sair.'),
]

def main():
 Path('outputs').mkdir(exist_ok=True)
 engine = TriageEngine(); rows=[]
 for lang,kind,text in CASES:
  start=perf_counter(); result=engine.triage({'lang':lang,'kind':kind,'messages':[{'role':'player','text':text}]}, synthetic=True)
  rows.append({'synthetic':True,'input':{'lang':lang,'kind':kind,'text':text},'latency_ms':round((perf_counter()-start)*1000,2),'ai_generated':any(r.startswith('Контекстный черновик') for r in result['reasons']),'result':result})
  print(lang, rows[-1]['ai_generated'], rows[-1]['latency_ms'], flush=True)
 delays=[r['latency_ms'] for r in rows]
 report={'model':engine.ai.model,'synthetic_only':True,'count':len(rows),'ai_generated':sum(r['ai_generated'] for r in rows),'needs_human_rate':sum(r['result']['needs_human'] for r in rows)/len(rows),'p50_ms':percentile(delays,.5),'p95_ms':percentile(delays,.95),'external_api_usd_per_ticket':None if engine.ai.backend == 'gemini' else 0,'hardware_cost':'Not monetized; hardware and electricity are not free.','rows':rows}
 Path('outputs/gemini_evaluation.json' if engine.ai.backend == 'gemini' else 'outputs/ai_evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 lines=['# Локальная ИИ-модель: измерения и примеры','',f"Модель: {report['model']}. Только {len(rows)} синтетических примеров; это проверка работы, не оценка точности на датасете.",'',f"ИИ-ответ принят: {report['ai_generated']}/{len(rows)}. Остальные — резервные шаблоны. needs_human: {report['needs_human_rate']:.1%}.",f"p50: {report['p50_ms']:.0f} мс; p95: {report['p95_ms']:.0f} мс. Модель могла быть прогрета предыдущими запросами; загрузка не измерялась отдельно. Стоимость внешнего API зависит от провайдера; для Gemini в этом скрипте не рассчитана. Оборудование и электричество отдельно, не оценены.",'','Языковое и смысловое качество требует оценки носителем, особенно kk/uz. Фильтры снижают риск, но не гарантируют отсутствие ошибок модели.']
 for row in rows:
  lines += ['',f"## {row['input']['lang']} · {'ИИ' if row['ai_generated'] else 'резерв'} · {row['latency_ms']:.0f} мс",'',row['input']['text'],'',row['result']['draft_reply']['text']]
 Path('outputs/gemini_evaluation.md' if engine.ai.backend == 'gemini' else 'outputs/ai_evaluation.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__': main()
