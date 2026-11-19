export const annotationClasses = {
  Normal: ['正常', '#215895'], Bent: ['弯曲', '#854600'], Deformed: ['形变', '#a13016'],
  Rusty: ['锈蚀', '#633f25'], Missing: ['缺失', '#a91c42'], Compromised: ['结构损伤', '#65349a']
}
const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

export function moveBox(box, mode, dx, dy, width, height) {
  const [left, top, right, bottom] = box
  if (mode === 'move') {
    const x = clamp(dx, -left, width - right), y = clamp(dy, -top, height - bottom)
    return [left + x, top + y, right + x, bottom + y]
  }
  const minW = Math.min(1, right-left), minH = Math.min(1, bottom-top)
  return [mode.includes('w') ? clamp(left + dx, 0, right - minW) : left,
    mode.includes('n') ? clamp(top + dy, 0, bottom - minH) : top,
    mode.includes('e') ? clamp(right + dx, left + minW, width) : right,
    mode.includes('s') ? clamp(bottom + dy, top + minH, height) : bottom]
}

export async function renderReviewedImage(originalUrl, edition) {
  const img = new Image()
  img.src = originalUrl
  await Promise.all([img.decode(), document.fonts.load('24px ReviewSong')])
  if (img.naturalWidth !== edition.width || img.naturalHeight !== edition.height)
    throw Error('原图尺寸与推理坐标不一致')
  const canvas = document.createElement('canvas')
  canvas.width = edition.width
  canvas.height = edition.height
  const ctx = canvas.getContext('2d')
  ctx.drawImage(img, 0, 0)
  const size = clamp(Math.round(Math.min(canvas.width, canvas.height)*.05), 12, 180)
  ctx.font = size+'px ReviewSong, serif'
  ctx.textBaseline = 'middle'
  const labels = []
  for (const {box:[x,y,r,b], label} of edition.targets) {
    const [text,color] = annotationClasses[label]
    const line = Math.max(2, size*.1)
    ctx.lineWidth = line+2
    ctx.strokeStyle = 'white'
    ctx.strokeRect(x,y,r-x,b-y)
    ctx.lineWidth = line
    ctx.strokeStyle = color
    ctx.strokeRect(x,y,r-x,b-y)
    labels.push({x,y,b,text,color})
  }
  const placed = []
  for (const {x,y,b,text,color} of labels) {
    const w = Math.ceil(ctx.measureText(text).width)+8, h = Math.ceil(size*1.25)
    const left = clamp(x,0,Math.max(0,canvas.width-w))
    const candidates = [y-h-1,b+1,y,y-2*h-2,b+h+2].map(n=>clamp(n,0,Math.max(0,canvas.height-h)))
    const overlap = top=>placed.reduce((sum,r)=>sum+Math.max(0,Math.min(left+w,r.right)-Math.max(left,r.left))*Math.max(0,Math.min(top+h,r.bottom)-Math.max(top,r.top)),0)
    const top = candidates.reduce((best,n)=>overlap(n)<overlap(best)?n:best)
    ctx.fillStyle=color
    ctx.fillRect(left,top,w,h)
    ctx.fillStyle='white'
    ctx.fillText(text,left+4,top+h/2,Math.max(1,canvas.width-8))
    placed.push({left,top,right:left+w,bottom:top+h})
  }
  return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob ? resolve(blob) : reject(Error('图片生成失败')),'image/jpeg',.94))
}
