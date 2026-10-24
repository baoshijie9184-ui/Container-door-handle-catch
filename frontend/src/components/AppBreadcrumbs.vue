<template>
  <nav class="app-breadcrumbs" aria-label="当前页面路径">
    <router-link v-if="parent" class="app-breadcrumb-back" :to="parent.path" :aria-label="'打开上级页面：'+parent.label" :title="'打开 '+parent.label"><AppIcon name="ArrowLeft" :size="14" /><span>{{ parent.label }}</span></router-link>
    <ol role="list">
      <li v-for="(crumb,index) in items" :key="(crumb.path || crumb.label)+':'+index" :class="{'is-current':index===items.length-1}">
        <span v-if="index" class="app-breadcrumb-separator" aria-hidden="true">/</span>
        <router-link v-if="crumb.path && index<items.length-1" :to="crumb.path" :title="crumb.label">{{ crumb.label }}</router-link>
        <span v-else :class="index===items.length-1 ? 'app-breadcrumb-current' : 'app-breadcrumb-group'" :aria-current="index===items.length-1 ? 'page' : undefined" :title="crumb.label">{{ crumb.label }}</span>
      </li>
    </ol>
  </nav>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
const props=defineProps({items:{type:Array,required:true}})
// Only reuse the ancestor links already admitted by the layout's role-aware metadata.
const parent=computed(()=>props.items.slice(0,-1).reverse().find(crumb=>typeof crumb.path==='string' && /^\/(?!\/)/.test(crumb.path)))
</script>
<style scoped>
.app-breadcrumbs{min-width:0;max-width:100%;color:var(--app-text);line-height:1.8}
.app-breadcrumbs ol{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 0;list-style:none;padding:0;margin:0;min-width:0}
.app-breadcrumbs li{display:inline-flex;align-items:baseline;gap:8px;min-width:0;max-width:100%;font-size:13px;line-height:1.8}
.app-breadcrumbs li+li{margin-left:8px}.app-breadcrumb-separator{color:var(--app-text-muted);font-size:12px;user-select:none;flex:0 0 auto}
.app-breadcrumbs li>a{color:var(--app-text-secondary);font-weight:400;text-decoration:none;overflow-wrap:anywhere;transition:color 180ms ease}
.app-breadcrumbs li>a:hover{color:var(--app-primary);text-decoration:underline;text-underline-offset:3px}
.app-breadcrumb-group{font-size:12px;color:var(--app-text-secondary);font-weight:400;overflow-wrap:anywhere}
.app-breadcrumb-current{font-size:14px;color:var(--app-text);font-weight:600;overflow-wrap:anywhere}
.app-breadcrumb-back{display:none}
.app-breadcrumbs a:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px;border-radius:3px}
@media(max-width:640px){
 .app-breadcrumbs{display:grid;gap:3px}
 .app-breadcrumbs ol{display:block}
 .app-breadcrumbs li:not(.is-current),.app-breadcrumbs .app-breadcrumb-separator{display:none}
 .app-breadcrumbs li.is-current{display:block;margin-left:0}
 .app-breadcrumb-back{display:inline-flex;align-items:center;gap:5px;min-height:26px;width:fit-content;max-width:100%;color:var(--app-primary);font-size:12px;line-height:1.7;text-decoration:none;transition:color 180ms ease}
 .app-breadcrumb-back>.el-icon{flex:0 0 auto;transition:transform 180ms ease}
 .app-breadcrumb-back>span{min-width:0;overflow-wrap:anywhere}
 .app-breadcrumb-back:hover{color:var(--app-primary-hover)}
 .app-breadcrumb-back:hover>.el-icon{transform:translateX(-1px)}
 .app-breadcrumb-current{font-size:14px;line-height:1.65;white-space:normal}
}
@media(prefers-reduced-motion:reduce){.app-breadcrumbs li>a,.app-breadcrumb-back,.app-breadcrumb-back>.el-icon{transition:none}.app-breadcrumb-back:hover>.el-icon{transform:none}}
</style>
