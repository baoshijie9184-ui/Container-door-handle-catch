<template>
  <el-dialog v-model="visible" title="查找功能" class="workspace-finder-dialog" width="min(540px, calc(100% - 24px))" top="min(12vh, 100px)"
    append-to-body destroy-on-close @open-auto-focus="focusSearch">
    <div class="workspace-finder">
      <label class="finder-input"><AppIcon name="Search" /><input ref="input" v-model="query" aria-label="搜索功能"
        placeholder="输入要做的事，例如「看图」或「查人」" type="search" autocomplete="off"
        @keydown.down.prevent="focusResult(0)" @keydown.enter="openFirst" /></label>
      <div ref="list" class="finder-results" @keydown.down="move($event,1)" @keydown.up="move($event,-1)">
        <template v-for="(item,index) in results" :key="item.group+item.label">
          <h3 v-if="index===0 || results[index-1].group!==item.group">{{ item.group }}</h3>
          <router-link :to="actionLocation(item)" @click="choose(item)">
            <span class="finder-symbol"><AppIcon v-if="item.icon" :name="item.icon" :size="16" /><el-icon v-else><component :is="item.symbol" /></el-icon></span>
            <span>{{ item.label }}</span><AppIcon name="ArrowRight" :size="14" />
          </router-link>
        </template>
        <p v-if="!results.length" role="status">没有找到匹配的功能。<button type="button" @click="reset">清空搜索</button></p>
      </div>
    </div>
  </el-dialog>
</template>
<script setup>
import {ref,computed,watch,onMounted,onBeforeUnmount} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {actionLocation,findWorkspaceActions} from '@/utils/workspaceActions'
const props=defineProps({groups:{type:Array,required:true},role:String})
const visible=ref(false),query=ref(''),input=ref(null),list=ref(null)
const router=useRouter(),route=useRoute()
const results=computed(()=>findWorkspaceActions(props.groups,props.role,query.value))
function open(){query.value='';visible.value=true}
function focusSearch(){input.value?.focus()}
function reset(){query.value='';focusSearch()}
function focusResult(index){list.value?.querySelectorAll('a')[index]?.focus()}
function move(event,direction){
  const links=Array.from(list.value.querySelectorAll('a')),index=links.indexOf(document.activeElement)
  if(index<0)return
  event.preventDefault()
  if(index===0 && direction<0)focusSearch()
  else focusResult(Math.min(index+direction,links.length-1))
}
function choose(item){if(router.resolve(actionLocation(item)).fullPath===route.fullPath)visible.value=false}
function openFirst(event){
  if(event.isComposing || event.keyCode===229 || !results.value.length)return
  event.preventDefault()
  list.value?.querySelector('a')?.click()
}
function shortcut(event){
  if(!(event.ctrlKey||event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase()!=='k')return
  const otherDialog = Array.from(document.querySelectorAll('dialog[open], [role="dialog"]'))
    .some(el => !el.closest('.workspace-finder-dialog') && el.getClientRects().length)
  if(otherDialog)return
  event.preventDefault()
  if(visible.value)focusSearch()
  else open()
}
watch(()=>route.fullPath,()=>{visible.value=false})
watch(query,()=>{if(list.value)list.value.scrollTop=0})
watch(()=>props.role,()=>{visible.value=false})
onMounted(()=>window.addEventListener('keydown',shortcut))
onBeforeUnmount(()=>window.removeEventListener('keydown',shortcut))
defineExpose({open})
</script>
<style>
.workspace-finder-dialog.el-dialog {padding:22px;border-radius:14px;max-height:85dvh;overflow:auto}
.workspace-finder-dialog .el-dialog__header {padding-bottom:14px}
.workspace-finder-dialog .el-dialog__title {font-size:20px;font-weight:650}
.finder-input {display:flex;align-items:center;gap:10px;padding:0 13px;background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:8px;color:var(--app-primary)}
.finder-input:focus-within {outline:2px solid var(--app-primary);outline-offset:1px}
.finder-input input {border:0;outline:none;background:transparent;flex:1;min-width:0;height:44px;font:inherit;font-size:16px;color:var(--app-text)}
.workspace-finder-dialog .finder-input input:focus-visible {outline:none;box-shadow:none}
.finder-results {overflow-y:auto;overscroll-behavior:contain;max-height:min(52dvh,480px);margin-top:12px;padding:2px 4px}
.finder-results h3 {color:var(--app-text-muted);font-size:12px;font-weight:600;margin:13px 7px 5px}
.finder-results a {display:flex;align-items:center;gap:12px;min-height:40px;padding:5px 8px;border-radius:6px;color:var(--app-text);text-decoration:none;font-size:14px}
.finder-results a:hover,.finder-results a:focus-visible {background:var(--app-primary-soft);color:var(--app-primary)}
.finder-results a:focus-visible {outline:2px solid var(--app-primary);outline-offset:-2px}
.finder-symbol {width:26px;display:grid;place-items:center;color:var(--app-primary)}
.finder-results a>.el-icon:last-child {margin-left:auto;color:var(--app-text-muted)}
.finder-results p {padding:14px 4px}
.finder-results p button {background:transparent;border:0;color:var(--app-primary);font:inherit;cursor:pointer}
</style>
