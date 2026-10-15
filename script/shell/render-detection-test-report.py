"""Create local review artifacts from a completed, real-image inference validation."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone, timedelta
import html
import json
from pathlib import Path
import statistics
import shutil

from PIL import Image, ImageDraw, ImageFont, ImageOps

NAMES=['Normal','Bent','Deformed','Rusty','Missing','Compromised']
ZH=['正常','弯曲','变形','锈蚀','缺失','损坏']
COLORS=['#1677ff','#d97706','#e85d04','#9a6324','#dc2626','#7c3aed']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.validation.read_text(encoding='utf-8'))
    is_pth=report.get('format')=='pth'
    if not report.get('passed') or report['imageCount']!=len(report['images']):
        raise ValueError('Only render complete, successful inference validation')
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    (out/'originals').mkdir(exist_ok=True);(out/'annotated').mkdir(exist_ok=True);(out/'predictions').mkdir(exist_ok=True)
    records=[];counts=Counter();image_counts=Counter();panels=[]
    for index,item in enumerate(report['images'],1):
        path=Path(item['image']);image=ImageOps.exif_transpose(Image.open(path)).convert('RGB')
        name=f'{index:03d}.jpg'
        original_name=f'{index:03d}{path.suffix.lower()}'
        shutil.copy2(path,out/'originals'/original_name)
        draw=ImageDraw.Draw(image);font_size=max(14,round(max(image.size)/60))
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',font_size)
        for detection in item['detections']:
            label=detection['label'];class_index=NAMES.index(label);color=COLORS[class_index]
            box=detection['box'];text=f"{label} {detection['score']:.3f}"
            draw.rectangle(box,outline=color,width=max(2,font_size//6))
            x,y=box[:2];y=max(0,y-font_size-6)
            bounds=draw.textbbox((x,y),text,font=font)
            draw.rectangle((bounds[0]-2,bounds[1]-2,bounds[2]+2,bounds[3]+2),fill='white')
            draw.text((x,y),text,font=font,fill=color)
            counts[label]+=1
        image_counts.update(set(d['label'] for d in item['detections']))
        image.save(out/'annotated'/name,quality=92)
        record={**item,'index':index,'filename':path.name,'original':f'originals/{original_name}','annotated':f'annotated/{name}'}
        (out/'predictions'/f'{index:03d}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append(record)
        preview=image.copy();preview.thumbnail((300,210))
        panels.append((preview.copy(),path.name,', '.join(sorted(set(d['label'] for d in item['detections']))) or 'No detection'))
    timings={kind:{'meanMs':round(statistics.mean(r[kind+'Ms'] for r in records),3),
                   'medianMs':round(statistics.median(r[kind+'Ms'] for r in records),3),
                   'p95Ms':round(sorted(r[kind+'Ms'] for r in records)[min(len(records)-1,int(.95*len(records)))],3)}
             for kind in (['torch'] if is_pth else ['torch','onnx'])}
    summary={'testedAt':datetime.now(timezone(timedelta(hours=8))).isoformat(),'imageCount':len(records),
        'successfulImages':len(records),'failedImages':0,'threshold':report['threshold'],
        'imagesWithDetections':sum(bool(r['detections']) for r in records),
        'imagesWithoutDetections':sum(not r['detections'] for r in records),
        'detectionBoxes':sum(counts.values()),'boxesPerClass':dict(counts),'imagesPerClass':dict(image_counts),
        'timing':timings,'cpuThreads':report['cpuThreads'],'format':'pth' if is_pth else 'onnx',
        'loadReport':report.get('loadReport'),'repeatabilityPassed':report.get('repeatabilityPassed'),
        'parityPassedImages':None if is_pth else len(records),
        'imagesWithTopKOrderDifferences':None if is_pth else sum(not r['allTopKLabelsSameOrder'] for r in records),
        'maxVisibleBoxErrorPixels':None if is_pth else max(r['boxMaxAbsErrorPixels'] for r in records),
        'maxVisibleScoreError':None if is_pth else max(r['scoreMaxAbsError'] for r in records),'apEvaluated':False,
        'accuracyEvaluated':False,'metricsLimit':('No matched ground-truth annotations were used; native PTH inference and repeatability only' if is_pth else 'No matched ground-truth annotations were used; inference and export parity only')}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'results.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['index','filename','boxes','classes','top_confidence','torch_ms','onnx_ms','inference_passed'])
        for r in records:
            writer.writerow([r['index'],r['filename'],len(r['detections']),','.join(sorted(set(d['label'] for d in r['detections']))),
                             max((d['score'] for d in r['detections']),default=0),r['torchMs'],r.get('onnxMs'),r['passed']])
    # A compact visual sample supplements the gallery, which contains all images.
    sheet=Image.new('RGB',(1280,1120),'#eef3fa');draw=ImageDraw.Draw(sheet)
    caption_font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',13)
    indices=[]
    for label in NAMES:
        indices.extend([i for i,r in enumerate(records) if label in {d['label'] for d in r['detections']} and i not in indices][:2])
    indices=(indices+[i for i in range(len(records)) if i not in indices])[:16]
    for cell,index in enumerate(indices):
        preview,filename,labels=panels[index];x=(cell%4)*320;y=(cell//4)*280
        sheet.paste(preview,(x+(320-preview.width)//2,y+8))
        draw.text((x+10,y+224),f'{index+1:03d} {filename[:28]}',font=caption_font,fill='#17243b')
        draw.text((x+10,y+246),labels,font=caption_font,fill='#1677ff')
    sheet.save(out/'contact-sheet.jpg',quality=92)
    rows='\n'.join(f'| {zh} / {name} | {counts[name]} | {image_counts[name]} |' for name,zh in zip(NAMES,ZH))
    validation_notes=(f"- 直接使用 .pth 和原始 EMA 模型，未进行 ONNX 转换或部署融合。严格加载 {report['loadReport']['stateTensors']} 个状态张量，无缺失或额外参数，重复运行检查通过。\n"
                      f"- 本地 CPU、2 个计算线程，PyTorch 平均 {timings['torch']['meanMs']:.1f} ms/张，P95 {timings['torch']['p95Ms']:.1f} ms/张。仅模型与后处理，不含读图、绘图、上传和网络，不代表 ECS 性能。"
                      if is_pth else
                      f"- 原始 EMA PyTorch 与 ONNX：全部原始 logits/boxes 数值核对及阈值以上检测集合核对通过 {len(records)} 张。\n"
                      f"- 可见框最大坐标误差 {summary['maxVisibleBoxErrorPixels']:.6f} 像素，置信度最大误差 {summary['maxVisibleScoreError']:.9f}。\n"
                      f"- PyTorch 平均 {timings['torch']['meanMs']:.1f} ms/张，ONNX 平均 {timings['onnx']['meanMs']:.1f} ms/张；不代表端到端或 ECS 性能。")
    markdown=f'''# 100 张门把手图片测试

测试时间：{summary['testedAt']}。从用户目录 2,913 张图片中按 seed=42 抽样，清单见 sample.json。未修改原始图片。

- 成功推理 {len(records)}/100 张，失败 0 张，置信度阈值 {report['threshold']}。
- 检测到对象的图片 {summary['imagesWithDetections']} 张，未检出 {summary['imagesWithoutDetections']} 张，共 {summary['detectionBoxes']} 个框。
{validation_notes}
- 本轮没有使用匹配的人工标注，不计算准确率、召回率或 mAP。检出框数不代表正确检出数；未检出不等于正常。

| 类别 | 检测框数 | 包含该类别的图片数 |
| --- | --- | --- |
{rows}

打开 index.html 查看全部标注图和原图，predictions/ 为逐张结果，results.csv 为汇总表，contact-sheet.jpg 为 16 张示例。
'''
    (out/'测试报告.md').write_text(markdown,encoding='utf-8')
    data=json.dumps({'summary':summary,'records':records},ensure_ascii=False).replace('</','<\\/')
    template='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>100 张图片检测测试</title>
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#17243b;background:#f3f6fb}*{box-sizing:border-box}body{margin:0}main{max-width:1440px;margin:auto;padding:32px 24px}h1{font-size:28px;margin:0 0 12px}p{line-height:1.7}.muted{color:#53647e}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.stat,.card{background:white;border:1px solid #e0e8f3;border-radius:14px}.stat{padding:20px}.stat strong{font-size:26px;display:block;color:#1677ff}.toolbar{position:sticky;top:0;background:#f3f6fbf5;padding:16px 0;z-index:2;display:flex;gap:12px;flex-wrap:wrap}input,select,button{font:inherit;border:1px solid #b8c9e2;border-radius:8px;padding:10px 12px;background:white;color:#17243b}input{flex:1;min-width:180px}button{cursor:pointer;transition:transform .15s,background .15s}button:hover{background:#eaf2ff;transform:scale(1.015)}button:active{transform:scale(.985)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #84b9ff;outline-offset:2px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}.card{overflow:hidden;animation:appear .2s ease}.card button{width:100%;padding:0;border:0;border-radius:0;background:white;text-align:left}.card img{width:100%;height:230px;object-fit:contain;background:#edf1f7}.info{padding:14px}.name{font-size:12px;overflow-wrap:anywhere}.labels{font-weight:600;margin:10px 0;font-size:14px}.meta{font-size:12px;color:#53647e}dialog{border:0;border-radius:16px;width:min(1100px,95vw);max-height:95vh;padding:20px}dialog::backdrop{background:#14233dbb}dialog img{max-width:100%;max-height:74vh;display:block;margin:12px auto;object-fit:contain}#detail-title{overflow-wrap:anywhere;font-size:14px}.dialog-tools{display:flex;gap:10px;justify-content:space-between}.notice{background:#eaf2ff;border-left:4px solid #1677ff;padding:14px 18px;border-radius:8px}footer{margin:24px 0;font-size:13px;color:#53647e}@keyframes appear{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}@media(max-width:650px){main{padding:20px 12px}.stats{grid-template-columns:repeat(2,1fr)}h1{font-size:24px}.toolbar{gap:8px}.card img{height:260px}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style><main><h1>100 张图片检测测试</h1><p class="muted">WACGA Shrinkage · EMA 权重 · 本地 CPU · 随机种子 42 · 置信度阈值 0.50</p><p class="notice">本轮验证推理与模型转换一致性，没有使用匹配的人工标注。检出数量不代表准确率，未检出也不等于正常。</p><section id="stats" class="stats" aria-label="测试汇总"></section><div class="toolbar"><input id="search" aria-label="搜索图片文件名" placeholder="搜索图片文件名"><select id="classes" aria-label="按检出类别筛选"><option value="all">全部类别</option><option value="empty">未检出对象</option></select><button id="mode" type="button">切换为原图</button></div><p id="count" role="status"></p><section id="grid" class="grid" aria-label="检测结果"></section><footer>标注图采用固定阈值 0.50，类别筛选控制展示哪些图片。单张耗时仅含模型与后处理；此报告不代表服务器或端到端性能。</footer></main><dialog id="detail"><div class="dialog-tools"><span id="detail-title"></span><button id="close">关闭</button></div><img id="detail-image" alt="检测结果大图"><p id="detail-predictions"></p></dialog><script>
const DATA=__DATA__;
const names=['Normal','Bent','Deformed','Rusty','Missing','Compromised'],zh=['正常','弯曲','变形','锈蚀','缺失','损坏'];
let original=false;const $=id=>document.getElementById(id);const summary=DATA.summary;const native=summary.format==='pth';
for(const [value,label] of [[summary.successfulImages+'/100','推理成功'],[summary.detectionBoxes,'检测框'],[native?summary.loadReport.stateTensors:summary.parityPassedImages+'/100',native?'严格加载的状态张量':'两套引擎核对通过'],[(native?summary.timing.torch:summary.timing.onnx).meanMs.toFixed(1)+' ms',native?'PTH 平均单张耗时':'ONNX 平均单张耗时']]){const box=document.createElement('div');box.className='stat';const strong=document.createElement('strong');strong.textContent=value;box.append(strong,document.createTextNode(label));$('stats').append(box)}
names.forEach((n,i)=>{const option=new Option(zh[i]+' / '+n,n);$('classes').add(option)});
function show(row){$('detail-title').textContent=row.index+' · '+row.filename;$('detail-image').src=original?row.original:row.annotated;$('detail-predictions').textContent=row.detections.map(d=>zh[names.indexOf(d.label)]+' '+(d.score*100).toFixed(1)+'%').join(' · ')||'该阈值下未检出对象';$('detail').showModal()}
function render(){const query=$('search').value.toLowerCase(),cls=$('classes').value;const rows=DATA.records.filter(r=>r.filename.toLowerCase().includes(query)&&(cls==='all'||(cls==='empty'?!r.detections.length:r.detections.some(d=>d.label===cls))));$('count').textContent='显示 '+rows.length+' / '+DATA.records.length+' 张';$('grid').replaceChildren();for(const row of rows){const card=document.createElement('article');card.className='card';const button=document.createElement('button');button.type='button';button.setAttribute('aria-label','查看图片 '+row.index);const img=document.createElement('img');img.loading='lazy';img.src=original?row.original:row.annotated;img.alt='图片 '+row.index+' '+(original?'原图':'检测标注');button.append(img);button.onclick=()=>show(row);const info=document.createElement('div');info.className='info';for(const [className,text] of [['name',row.index+' · '+row.filename],['labels',row.detections.map(d=>zh[names.indexOf(d.label)]+' '+(d.score*100).toFixed(1)+'%').join(' · ')||'未检出对象'],['meta',row.detections.length+' 个框 · '+(native?'PTH '+row.torchMs.toFixed(1):'ONNX '+row.onnxMs.toFixed(1))+' ms · 正常输出']]){const e=document.createElement('div');e.className=className;e.textContent=text;info.append(e)}card.append(button,info);$('grid').append(card)}}
$('search').oninput=render;$('classes').onchange=render;$('mode').onclick=()=>{original=!original;$('mode').textContent=original?'切换为标注图':'切换为原图';render()};$('close').onclick=()=>$('detail').close();render();
</script></html>'''
    (out/'index.html').write_text(template.replace('__DATA__',data).replace('本轮验证推理与模型转换一致性','本轮验证原始 PTH 推理与重复执行一致性' if is_pth else '本轮验证推理与模型转换一致性'),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
