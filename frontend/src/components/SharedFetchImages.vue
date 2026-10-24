<template>
  <section class="shared-fetch-images" aria-labelledby="shared-fetch-title">
    <header><div class="title"><el-icon><Box /></el-icon><div><h3 id="shared-fetch-title">共享运行镜像</h3><p>主管管理 · 核对全系统引用后回收</p></div></div><el-button :loading="loading" :disabled="busy" @click="refresh"><el-icon><Refresh /></el-icon>刷新核对</el-button></header>
    <p>当前镜像、仍被账号引用的版本及未退出执行不能回收 许可证独立归档 不按镜像大小推算磁盘释放或费用</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <template v-if="state">
      <div class="archive-metric"><el-icon><DocumentChecked /></el-icon><span>已保留许可证归档</span><strong>{{ bytes(state.legalArchiveBytes) }}</strong></div>
      <p v-if="state.writesEnabled===false" class="notice">新回收已暂停 仍可查看历史及只读核对原回收结果</p>
      <p v-if="state.cleanupAllowed!==true" class="notice">当前环境仅能观察共享镜像 不开放宿主镜像删除</p>
      <TransitionGroup name="image-row" tag="div" class="images">
        <article v-for="item in state.items || []" :key="item.image" :class="{review:item.state==='NEEDS_REVIEW'}">
          <div class="image-heading"><strong>{{ item.current?'当前固定 Fetch':'历史固定 Fetch' }}</strong><el-tag :type="item.state==='REMOVED'?'success':item.state==='ACTIVE'?'info':'warning'">{{ label(item.state) }}</el-tag></div>
          <code class="digest">{{ item.image }}</code>
          <div class="metrics"><span>镜像逻辑大小 <b>{{ bytes(item.imageBytes) }}</b></span><span>运行器观察 <b>{{ item.present===true?'镜像存在':item.present===false?'镜像不存在':'未知' }}</b></span></div>
          <dl class="references"><div v-for="(value,key) in item.references || {}" :key="key"><dt>{{ referenceLabel(key) }}</dt><dd>{{ typeof value==='number'?value:'未知' }}</dd></div></dl>
          <p v-if="item.archiveSha256" class="legal"><el-icon><CircleCheck /></el-icon>许可证归档摘要 <code>{{ item.archiveSha256 }}</code></p>
          <p v-if="item.state!=='ACTIVE'&&item.state!=='REMOVED'">已封存新引用 结果未核实前保留记录 不自动重试删除</p>
          <footer><time v-if="item.updatedAt">{{ beijingDateTime(item.updatedAt) }} UTC+8</time><div class="actions"><el-button v-if="item.canRequestCleanup" type="primary" :disabled="busy" @click="act(item,'cleanup')"><el-icon><Delete /></el-icon>回收无引用镜像</el-button><el-button v-if="!['ACTIVE','REMOVED'].includes(item.state)" :disabled="busy" @click="act(item,'reconcile')"><el-icon><Search /></el-icon>只读核对结果</el-button></div></footer>
        </article>
      </TransitionGroup>
      <el-empty v-if="!state.items?.length" description="尚无可显示的共享镜像" />
    </template>
  </section>
</template>
<script setup>
import { ref,onMounted,onBeforeUnmount } from 'vue'
import { Box,Refresh,DocumentChecked,CircleCheck,Delete,Search } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import request from '@/api/request'
import { beijingDateTime } from '@/utils/beijingTime'
const state=ref(null),loading=ref(false),busy=ref(false),error=ref(''),notice=ref('')
let mounted=true,generation=0,promptOpen=false
const labels={ACTIVE:'尚未回收',RETIRING:'封存核对中',DELETING:'回收中',REMOVED:'已核实回收',NEEDS_REVIEW:'结果待核对'}
const label=value=>labels[value]||'状态未知'
const bytes=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?`${(value/1048576).toFixed(2)} MiB`:'未知'
const referenceLabel=key=>({deploymentBaselineUnverified:'部署基线待核实',deploymentRetained:'部署及恢复保留',registrations:'当前账号登记',unknownRegistrations:'登记资料待核实',retainedOrUnverified:'回退保留或安装待核实',unknownSnapshots:'历史快照待核实',pendingExecutions:'执行或退出待核实',pendingInstallations:'全系统待结束安装'}[key]||'其他引用')
async function refresh(){
  const token=++generation;loading.value=true;error.value=''
  try{const result=await request.get('/api/agent/mcp/fetch/shared-images',{timeout:90000});if(mounted&&token===generation)state.value=result.data}
  catch(e){if(mounted&&token===generation){if(e.response?.status===403)state.value=null;error.value=e.response?.data?.message||'共享镜像状态暂时无法核对 未知数据不会按零处理'}}
  finally{if(mounted&&token===generation)loading.value=false}
}
async function act(item,action){
  if(busy.value)return
  const command={image:item.image,expectedRevision:item.revision,requestId:crypto.randomUUID(),confirmed:true}
  busy.value=true;error.value='';notice.value='';promptOpen=true
  try{
    await ElMessageBox.confirm(action==='cleanup'?'回收这个共享 Fetch 镜像。服务器会再次核对所有账号的引用，独立归档许可证，再提交一次删除；结果未知时不会自动重做。':'只查询原运行器回执与现存资源，不重新归档，也不再次发送删除请求。',action==='cleanup'?'确认回收无引用镜像':'确认只读核对',{confirmButtonText:action==='cleanup'?'确认回收':'只读核对',cancelButtonText:'取消',closeOnClickModal:false})
    promptOpen=false;if(!mounted)return
    await request.post(`/api/agent/mcp/fetch/shared-images/${action}`,command,{headers:{'X-MCP-Action':'update'},timeout:180000})
    if(mounted){notice.value=`操作已提交 请以刷新后的核对状态为准 请求编号 ${command.requestId}`;await refresh()}
  }catch(e){
    if(mounted&&e!=='cancel'&&e!=='close'){error.value=e.response?.data?.message||'操作结果尚未核实 请刷新或只读核对 不会自动重发删除';notice.value=`本次请求编号 ${command.requestId}`}
  }finally{promptOpen=false;if(mounted)busy.value=false}
}
onMounted(refresh)
onBeforeUnmount(()=>{mounted=false;generation++;if(promptOpen)ElMessageBox.close()})
</script>
<style scoped>
.shared-fetch-images{padding:22px;border:1px solid #cddff5;border-radius:18px;background:linear-gradient(140deg,#f4f9ff,#fff 65%);color:#172b4d}
header,.title,.image-heading,footer,.actions,.legal,.archive-metric{display:flex;align-items:center;gap:10px}header,footer,.image-heading{justify-content:space-between}.title>.el-icon{padding:12px;box-sizing:content-box;border-radius:14px;background:#e1edff;color:#2864c6;font-size:24px}h3{margin:0;font-size:18px}p{color:#52647d;font-size:13px;line-height:1.7}.title p{margin:4px 0 0}.images{display:grid;gap:14px;margin-top:16px}.images article{padding:18px;border:1px solid #dbe5f2;border-radius:14px;background:white;transition:border-color .2s,box-shadow .2s}.images article:hover{border-color:#94b6eb;box-shadow:0 5px 20px #1e4c8910}.images article.review{border-color:#e5cfa0}.digest,.legal code{overflow-wrap:anywhere;word-break:break-all;white-space:normal}.digest{display:block;margin:12px 0;font-size:12px}.metrics{display:flex;flex-wrap:wrap;gap:16px;font-size:12px;color:#5e7087}.metrics b{margin-left:6px;color:#243d60}.references{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.references div{padding:9px;border-radius:9px;background:#f3f7fc}.references dt{font-size:11px;color:#60718a}.references dd{margin:6px 0 0;font-size:17px;font-weight:600}.archive-metric{padding:12px;border-radius:12px;background:#eaf3ff;font-size:13px}.archive-metric .el-icon{color:#2f67c4}.archive-metric strong{margin-left:auto}.error{color:#b42318}.notice{padding:10px 12px;border-left:3px solid #4380d7;background:#edf4ff;border-radius:6px;overflow-wrap:anywhere}footer time{font-size:11px;color:#6b7c93}.legal{align-items:flex-start;color:#267656;font-size:12px}.legal code{min-width:0}.actions{flex-wrap:wrap}.el-button{transition:transform .16s,box-shadow .16s}.el-button:hover:not(:disabled){transform:translateY(-1px)}.el-button:active:not(:disabled){transform:scale(.98)}.el-button:focus-visible{outline:3px solid #aacaff;outline-offset:3px}.image-row-enter-active,.image-row-leave-active,.image-row-move{transition:opacity .18s,transform .18s}.image-row-enter-from,.image-row-leave-to{opacity:0;transform:translateY(5px)}@media(max-width:650px){.shared-fetch-images{padding:14px}header,footer{align-items:flex-start;flex-direction:column}.references{grid-template-columns:repeat(2,minmax(0,1fr))}.image-heading{gap:8px;align-items:flex-start}.metrics{gap:8px}.archive-metric{flex-wrap:wrap}.archive-metric strong{margin-left:0}.actions{width:100%}.actions .el-button{margin:0}}@media(prefers-reduced-motion:reduce){*,.image-row-enter-active,.image-row-leave-active,.image-row-move{transition:none!important;transform:none!important}}
</style>
