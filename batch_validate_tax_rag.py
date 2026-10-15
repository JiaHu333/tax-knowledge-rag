"""Batch-run the actual fixed menu against local Chroma/Ollama.

Uses the project's existing Python environment. It does not edit ask.py,
ingest.py, documents, or call ingest. Logs are saved under --out.
"""
import argparse
import builtins
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import runpy
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_config(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema') != 1:
        raise ValueError('不支持的菜单配置版本；未启动任何测试。')
    if not {'topic_config','topic_menu_options'} <= data.keys():
        raise ValueError('配置缺少菜单字段；未启动任何测试。')
    return {
        'TOPIC_CONFIG': data['topic_config'],
        'TOPIC_MENU_OPTIONS': data['topic_menu_options'],
    }


def routes(config):
    result = []
    for menu_key, menu in config['TOPIC_MENU_OPTIONS'].items():
        topic = config['TOPIC_CONFIG'][menu['topic_name']]

        def leaves(node, keys, labels):
            children = node.get('subscenarios')
            if children:
                for key, child in children.items():
                    yield from leaves(child, keys+[key], labels+[child['label']])
            else:
                yield keys, labels, node

        for sk, base in topic['scenarios'].items():
            if not base.get('askable', True): continue
            for subkeys, labels, leaf in leaves(base, [], [base['label']]):
                merged = {**base, **leaf}
                taxes = merged.get('tax_types', topic['tax_types'])
                for tax in taxes:
                    reliefs = (merged.get('relief_scenarios', topic.get('relief_scenarios', {}))
                               if merged.get('needs_relief_question') and tax=='Withholding' else {})
                    for rk, relief in (reliefs or {None:{}}).items():
                        choices = [menu_key]
                        if not topic.get('default_scenario'): choices.append(sk)
                        ask_tax = merged.get('ask_tax_type', topic.get('ask_tax_type', True))
                        ti = str(taxes.index(tax)+1)
                        if topic.get('resolve_scenario_before_tax'):
                            choices.extend(subkeys)
                            if ask_tax: choices.append(ti)
                        else:
                            if ask_tax: choices.append(ti)
                            choices.extend(subkeys)
                        if rk: choices.append(rk)
                        full_labels = labels + ([relief['label']] if rk else [])
                        result.append({'id':'-'.join(choices), 'choices':choices,
                                       'topic_number':menu_key,'topic':menu['label'],
                                       'label':'；'.join(full_labels),'tax':tax})
    if len({r['id'] for r in result})!=len(result): raise ValueError('菜单路径编号重复。')
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_text_sha(path):
    """Ignore only CRLF/LF checkout differences in versioned text files."""
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def write_json(path, value):
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)


def worker(ask_path, config_path, db_path, choices, event_path):
    # Real project imports and real document-selection calls. Only input and
    # the selected-context observer are wrapped; answer text is untouched.
    event_path.parent.mkdir(parents=True,exist_ok=True)
    with event_path.open('w',encoding='utf-8') as events:
        def event(kind, **kwargs):
            events.write(json.dumps({'kind':kind,**kwargs},ensure_ascii=False,default=str)+'\n')
            events.flush()
        ns = runpy.run_path(str(ask_path),run_name='_tax_rag_validation_')
        global_ns = ns['main'].__globals__
        pending = list(choices)
        old_input = builtins.input
        def menu_input(prompt=''):
            choice = pending.pop(0) if pending else 'q'
            print(prompt+choice,flush=True)
            event('menu_input', choice=choice, prompt=prompt)
            return choice
        def docs_data(docs):
            return [{'metadata':dict(d.metadata),'text':d.page_content} for d in docs]
        old_selected = global_ns['print_selected_context']
        def selected(docs, mode):
            event('selected_context',mode=mode,documents=docs_data(docs))
            return old_selected(docs=docs,mode=mode)
        global_ns['print_selected_context'] = selected
        builtins.input = menu_input
        try:
            ns['main'](config_path=config_path, db_dir=db_path)
            event('finished',unconsumed_choices=pending)
            if pending: raise RuntimeError('脚本提前结束，菜单输入未全部使用：'+repr(pending))
        except BaseException as exc:
            event('exception',type=type(exc).__name__,message=str(exc))
            raise
        finally: builtins.input = old_input


def parse_output(stdout, stderr, returncode, timed_out):
    if timed_out: return {'status':'timeout','answer':'','note':'超时；已保留部分检索与日志，未判为税务无答案。'}
    if returncode: return {'status':'error','answer':'','note':stderr[-1500:]}
    match = re.search(r'\nAnswer:\s*\n(.*?)\nRetrieval Time:',stdout,re.S)
    if match:
        retrieval = re.search(r'Retrieval Time:\s*([\d.]+)s',stdout)
        generation = re.search(r'Generation Time:\s*([\d.]+)s',stdout)
        return {'status':'answer','answer':match.group(1).strip(),
                'output_mode':'Python' if 'Using selected knowledge-base text directly' in stdout else 'Ollama',
                'retrieval_seconds':float(retrieval.group(1)) if retrieval else None,
                'generation_seconds':float(generation.group(1)) if generation else None,
                'note':'已取得实际答案；内容与语义待对照文档验收。'}
    if any(s in stdout for s in ['Structured overview found no tax-specific','文档与简短答案规则不匹配','CIT 段落与简短答案规则不匹配','文档答案提取失败']):
        return {'status':'formatter_mismatch','answer':'','note':'已走直接输出但校验失败。'}
    if 'Structured selection found no matching' in stdout or 'No relevant documents found' in stdout:
        return {'status':'no_context','answer':'','note':'实际未获得可用上下文；仍需区分未收录与选段故障。'}
    return {'status':'no_answer','answer':'','note':'没有最终答案；查看日志中的重复中止或其他诊断。'}


def compare_standard_result(case, result, event_path, expected_cases):
    """Compare the observed runtime answer and source against the separate authored baseline."""
    reference = expected_cases.get(case["id"])
    if reference is None:
        return {"status": "validation_mismatch", "standard_check": "failed",
                "note": "当前菜单路径未收录在标准答案基线中。"}
    issues = []
    def normalized(text):
        # MarkdownHeaderTextSplitter may serialize an authored paragraph break
        # as a Markdown hard break (two trailing spaces plus one newline).
        # Compare the answer text independently of that presentation-only
        # whitespace while still requiring every non-whitespace character to
        # match the separately authored baseline.
        return re.sub(r"\s+", " ", text).strip()
    if result.get("status") != "answer":
        issues.append("未取得正常答案")
    if normalized(result.get("answer", "")) != normalized(reference["answer"]):
        issues.append("输出与标准答案不一致")
    if result.get("output_mode") != "Python":
        issues.append("输出未使用文档直读")
    selected = []
    for line in event_path.read_text(encoding="utf-8").splitlines() if event_path.exists() else []:
        record = json.loads(line)
        if record.get("kind") == "selected_context":
            selected.extend(record.get("documents", []))
    if not selected:
        issues.append("未记录标准答案来源")
    for doc in selected:
        metadata = doc.get("metadata", {})
        if metadata.get("source") != reference["source"]:
            issues.append("来源文件不匹配")
        if metadata.get("title") != "固定菜单标准答案" or metadata.get("heading_2") != "场景：" + reference["label"]:
            issues.append("标准答案场景章节不匹配")
        if metadata.get("tax_type") != reference["tax"] or metadata.get("heading_4"):
            issues.append("税种或补充说明选段错误")
    for term in reference.get("required", []):
        if term not in result.get("answer", ""):
            issues.append("缺少必需条件：" + term)
    if issues:
        return {"status": "validation_mismatch", "standard_check": "failed", "issues": list(dict.fromkeys(issues)),
                "note": "；".join(dict.fromkeys(issues))}
    return {"status": "deferred" if reference.get("status") == "deferred" else "passed",
            "standard_check": "passed", "note": "输出、来源和必需条件与标准答案一致；非独立税务审计。"}


def load_expected_baseline(path, root, ask, config, all_cases):
    baseline = json.loads(path.read_text(encoding="utf-8-sig"))
    if baseline.get("schema") != 1:
        raise ValueError("不支持的标准答案基线版本")
    if baseline_text_sha(ask) != baseline.get("ask_sha256"):
        raise ValueError("ask.py 与标准答案基线版本不一致；请使用同一交付版本")
    if baseline_text_sha(config) != baseline.get("config_sha256"):
        raise ValueError("config.json 与标准答案基线版本不一致；请使用同一交付版本")
    expected = {row["id"]: row for row in baseline["cases"]}
    if len(expected) != len(baseline["cases"]) or set(expected) != {r["id"] for r in all_cases}:
        raise ValueError("标准答案基线与当前菜单组合不一致")
    for name, checksum in baseline["documents"].items():
        files = [p for p in (root/"docs"/"CN").rglob(name) if p.is_file()]
        if len(files) != 1 or baseline_text_sha(files[0]) != checksum:
            raise ValueError("文档缺失、重复或与基线版本不一致：" + name + "；确认修改后需同步更新标准答案基线")
    return expected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path.cwd())
    p.add_argument('--ask',default='ask.py')
    p.add_argument('--config',default='config.json')
    p.add_argument('--db',default='db')
    p.add_argument('--ingest',default='ingest.py')
    p.add_argument('--out',type=Path,default=Path('tax_rag_validation'))
    p.add_argument('--expected',type=Path,help='独立标准答案基线；省略时自动使用项目下的demo_expected.json')
    p.add_argument('--topic',nargs='+',help='只测试这些主菜单编号，如 --topic 1 5')
    p.add_argument('--case',nargs='+',help='只测试路径编号，如 --case 5-2-3')
    p.add_argument('--timeout',type=int,default=300,help='每条路径最大秒数，默认300')
    p.add_argument('--resume',action='store_true',help='跳过同一轮已完成路径；超时/报错重试')
    p.add_argument('--list',action='store_true',help='只列菜单；不导入项目或调用模型')
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--choices',help=argparse.SUPPRESS)
    p.add_argument('--events',type=Path,help=argparse.SUPPRESS)
    args=p.parse_args()
    root=args.project.resolve()
    ask=Path(args.ask)
    ask=(root/ask).resolve() if not ask.is_absolute() else ask.resolve()
    config=Path(args.config)
    config=(root/config).resolve() if not config.is_absolute() else config.resolve()
    db=Path(args.db)
    db=(root/db).resolve() if not db.is_absolute() else db.resolve()
    ingest=Path(args.ingest)
    ingest=(root/ingest).resolve() if not ingest.is_absolute() else ingest.resolve()
    if args.worker:
        worker(ask,config,db,json.loads(args.choices),args.events)
        return
    if args.timeout<1: p.error('--timeout必须大于0')
    cfg=read_config(config)
    all_cases=routes(cfg)
    cases=[r for r in all_cases if (not args.topic or r['topic_number'] in args.topic)
           and (not args.case or r['id'] in args.case)]
    if not cases: p.error('指定范围没有菜单路径')
    if args.case and set(args.case)-{r['id'] for r in all_cases}: p.error('存在无效--case编号')
    if args.topic and set(args.topic)-set(cfg['TOPIC_MENU_OPTIONS']): p.error('存在无效--topic编号')
    print(f'有效菜单共{len(all_cases)}条，本次范围{len(cases)}条。')
    if args.list:
        for r in cases: print(r['id'],r['topic'],'→',r['label'],'→',r['tax'])
        return
    expected_path=(root/args.expected).resolve() if args.expected else root/'demo_expected.json'
    expected_cases=None
    if args.expected or expected_path.is_file():
        try: expected_cases=load_expected_baseline(expected_path,root,ask,config,all_cases)
        except (ValueError,OSError,KeyError) as exc: p.error(str(exc))
    if not db.is_dir(): p.error(f'未找到数据库目录{db}。请在实际项目目录运行；不会创建测试数据库。')
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    manifest_path=out/'manifest.json'
    docs={str(path.relative_to(root)):sha(path) for path in sorted((root/'docs'/'CN').rglob('*')) if path.is_file()}
    identity={'validator_sha256':sha(Path(__file__).resolve()),
              'ask_sha256':sha(ask),'config_sha256':sha(config),
              'ingest_sha256':sha(ingest) if ingest.is_file() else None,
              'document_hashes':docs,
              'expected_sha256':sha(expected_path) if expected_cases is not None else None}
    completed=[]
    results_path=out/'results.jsonl'
    if args.resume:
        if not manifest_path.exists(): p.error('续跑需要已有manifest.json，请先开始一轮测试')
        saved=json.loads(manifest_path.read_text(encoding='utf-8'))
        if saved['identity']!=identity: p.error('脚本或文档已改变，请换--out目录开始新一轮，避免混合版本。')
        if results_path.exists():
            for line in results_path.read_text(encoding='utf-8').splitlines():
                if line.strip(): completed.append(json.loads(line))
    elif results_path.exists() or manifest_path.exists():
        p.error('输出目录已有记录。请使用--resume或换一个--out目录。')
    else:
        packages={}
        for name in ['langchain-text-splitters','langchain-core','langchain-chroma','langchain-ollama','chromadb','ollama']:
            try: packages[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: packages[name]='未安装'
        try:
            version=subprocess.run(['ollama','--version'],capture_output=True,text=True,timeout=10)
            ollama_version=(version.stdout+version.stderr).strip()
        except (OSError,subprocess.TimeoutExpired) as exc: ollama_version=str(exc)
        write_json(manifest_path,{'started_at':datetime.now(timezone.utc).isoformat(),'project':str(root),
                                'python':sys.version,'platform':platform.platform(),'packages':packages,
                                'ollama_version':ollama_version,'identity':identity,'all_cases':all_cases,
                                'scope':'真实调用ask.main；仅包装菜单输入和已选上下文观测；不改选段与答案文本',
                                'database_note':'未记录数据库快照；同一轮续跑期间请保持数据库不变。'})
    done={r['id'] for r in completed if r['status'] not in {'timeout','error','interrupted'}}
    logs=out/'logs'; logs.mkdir(exist_ok=True)
    events=out/'events'; events.mkdir(exist_ok=True)
    env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
    print(f'结果目录：{out}\n每条超时{args.timeout}秒；可Ctrl+C中断，之后--resume继续。',flush=True)
    try:
        for i,case in enumerate(cases,1):
            if case['id'] in done:
                print(f'[{i}/{len(cases)}] 跳过已完成 {case["id"]}',flush=True)
                continue
            print(f'[{i}/{len(cases)}] {case["id"]} {case["label"]} / {case["tax"]}',flush=True)
            # Retry logs use a new attempt suffix so older evidence is retained.
            attempt=1+sum(r['id']==case['id'] for r in completed)
            stem=f'{case["id"]}_attempt{attempt}'
            event_path=events/(stem+'.jsonl')
            cmd=[sys.executable,'-u',str(Path(__file__).resolve()),'--worker','--project',str(root),
                 '--ask',str(ask),'--config',str(config),'--db',str(db),
                 '--choices',json.dumps(case['choices']),'--events',str(event_path)]
            started=time.monotonic()
            proc=subprocess.Popen(cmd,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                  text=True,encoding='utf-8',errors='replace')
            timed_out=False; interrupted=False
            try: stdout,stderr=proc.communicate(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;proc.kill();stdout,stderr=proc.communicate()
            except KeyboardInterrupt:
                interrupted=True;proc.kill();stdout,stderr=proc.communicate()
            (logs/(stem+'.stdout.txt')).write_text(stdout,encoding='utf-8')
            (logs/(stem+'.stderr.txt')).write_text(stderr,encoding='utf-8')
            result={**case,'attempt':attempt,'elapsed_seconds':round(time.monotonic()-started,2),
                    'returncode':proc.returncode,'stdout_log':f'logs/{stem}.stdout.txt',
                    'stderr_log':f'logs/{stem}.stderr.txt','events_log':f'events/{stem}.jsonl',
                    **parse_output(stdout,stderr,proc.returncode,timed_out)}
            if expected_cases is not None and not interrupted:
                result.update(compare_standard_result(case,result,event_path,expected_cases))
            if interrupted: result.update(status='interrupted',note='用户中断；保留已取得的证据。')
            with results_path.open('a',encoding='utf-8') as f:
                f.write(json.dumps(result,ensure_ascii=False)+'\n'); f.flush()
            completed.append(result)
            latest={r['id']:r for r in completed}
            write_json(out/'summary.json',{'total_menu_cases':len(all_cases),'recorded_cases':len(latest),
                                         'latest_status_counts':dict(Counter(r['status'] for r in latest.values())),
                                         'cases':list(latest.values()),'semantic_review':('已对照独立标准答案检查输出、来源及条件；非独立税务审计。' if expected_cases is not None else '待与最新版文档对照；answer不代表验收通过')})
            print(f'  {result["status"]}，{result["elapsed_seconds"]}秒',flush=True)
            if interrupted: raise KeyboardInterrupt
    except KeyboardInterrupt:
        print('\n已停止并保存；请使用相同--out及--resume继续。',flush=True)
        return
    print('本次范围运行结束。请检查summary.json中的passed/deferred/validation_mismatch；整个结果目录可压缩为ZIP用于复核。',flush=True)


if __name__=='__main__': main()
