<template>
  <section class="wb-files" aria-label="当前会话资料" :aria-busy="loading">
    <template v-if="known">
      <div class="wb-file-overview"><AppIcon name="Files" :size="18" /><div><strong>{{ summary.count }} 个私有文件</strong><span>已关联大小 {{ summary.size }}，非账号总用量</span></div></div>
      <p v-if="error" class="wb-note">读取未完成，以下保留上次已读取的资料，请刷新核对。</p>
      <p v-if="busy" class="wb-file-operation" role="status"><AppIcon name="Connection" :size="15" />工作台操作处理中，文件操作暂不可用。</p>
      <div v-if="files.length || businessFiles.length || query" class="wb-file-search"><label>查找会话资料<input v-model="query" type="search" maxlength="200" placeholder="文件名或编号" /></label><button v-if="query" type="button" @click="query=''">清空</button></div>
      <section v-if="businessRows.length" class="wb-business-references" aria-label="业务资料引用">
        <h4><AppIcon name="Connection" :size="16" />业务资料引用 <small>{{ businessRows.length }}</small></h4>
        <p class="wb-note">使用现有业务权限读取，不计入上方私有文件大小。</p>
        <article v-for="file in businessRows" :key="file.kind+file.resourceId+file.fileId" class="wb-file-row" :aria-label="'业务资料 '+(file.name || file.resourceId)">
          <div class="wb-file-heading"><span class="wb-file-icon"><AppIcon :name="file.kind==='REPORT'?'DocumentChecked':'Picture'" :size="19" /></span><div><strong>{{ file.name || '未记录文件名' }}</strong><small>{{ file.kind==='REPORT'?'质检报告':'检测资料' }} · {{ file.resourceId }}</small></div></div>
          <div class="wb-actions"><button type="button" :disabled="busy" @click="$emit('preview-business',file)"><AppIcon name="Search" :size="14" />预览业务文件</button></div>
        </article>
      </section>
      <details v-for="folder in visibleGroups" :key="folder.key" open class="wb-file-tree">
        <summary><AppIcon :name="folder.icon" :size="16" /><span>{{ folder.label }}</span><small>{{ folder.files.length }}</small><AppIcon name="ArrowRight" :size="12" class="wb-folder-chevron" /></summary>
        <p class="wb-note">{{ folder.note }}</p>
        <article v-for="file in folder.files" :key="file.id" class="wb-file-row" :aria-label="'私有文件 '+(file.name || file.id)">
          <div class="wb-file-heading"><span class="wb-file-icon"><AppIcon :name="composerAttachment(file).icon" :size="19" /></span><div><strong>{{ file.name || '未记录文件名' }}</strong><small>{{ composerAttachment(file).type }} · {{ composerAttachment(file).size }}</small></div></div>
          <div class="wb-actions"><button type="button" :disabled="busy" @click="$emit('preview',file)"><AppIcon name="Search" :size="14" />预览</button><button type="button" :disabled="busy" @click="$emit('download',file)"><AppIcon name="Download" :size="14" />下载</button><button v-if="!folder.readOnly" type="button" :disabled="busy" @click="$emit('reference',file)"><AppIcon name="Plus" :size="14" />引用</button></div>
          <details class="wb-file-more"><summary :aria-label="(file.name||'文件')+'的编号与更多操作'">更多</summary><p class="wb-file-id">文件编号 {{ file.id }}</p><div v-if="!folder.readOnly" class="wb-actions"><button type="button" :disabled="busy" @click="$emit('copy',file)"><AppIcon name="DocumentCopy" :size="14" />复制引用</button><button type="button" class="wb-button-danger" :disabled="busy" @click="$emit('remove',file)"><AppIcon name="Delete" :size="14" />移出会话</button></div></details>
        </article>
      </details>
      <div v-if="!visibleGroups.length&&!businessRows.length" class="wb-empty"><AppIcon :name="query.trim()?'Search':'Files'" :size="24" /><strong>{{ query.trim()?'没有匹配的资料':'当前会话尚无资料' }}</strong><p>{{ query.trim()?'可调整文件名或编号，或清空搜索。':'可以上传本人资料，或关联有权读取的检测任务与报告。' }}</p><button v-if="query.trim()" type="button" @click="query=''">清空搜索</button></div>
    </template>
    <div v-else class="wb-empty"><AppIcon :name="error?'Warning':'Connection'" :size="24" /><strong>{{ error?'资料暂不可读取':'正在读取会话资料' }}</strong><p>{{ error?'请刷新核对，不根据空列表推断文件已删除。':'读取完成后显示已关联的文件与业务资料。' }}</p></div>
  </section>
</template>
<script setup>
import { computed,ref } from 'vue'
import { composerAttachment } from '@/utils/composerPresentation'
import { workbenchFileGroups,workbenchFileMatches,workbenchFileSummary } from '@/utils/workbenchPresentation'
const props=defineProps({files:{type:Array,default:()=>[]},businessFiles:{type:Array,default:()=>[]},busy:Boolean,known:Boolean,loading:Boolean,error:String})
defineEmits(['preview','download','reference','copy','remove','preview-business'])
const query=ref('')
const summary=computed(()=>workbenchFileSummary(props.files))
const visibleGroups=computed(()=>workbenchFileGroups(props.files,query.value).filter(group=>group.files.length))
const businessRows=computed(()=>props.businessFiles.filter(file=>workbenchFileMatches(file,query.value)))
</script>
