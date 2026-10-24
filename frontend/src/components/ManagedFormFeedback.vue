<template>
  <div class="managed-form-feedback">
    <p class="managed-form-state" role="status">
      <StatusBadge v-if="receipt" domain="apiReceipt" :code="receipt.state" />
      <AppIcon v-else :name="phase==='READING' ? 'Refresh' : dirty ? 'Edit' : 'Document'" :size="16" />
      <span>{{ phase==='READING' ? '正在读取资料与版本' : phase==='VALIDATING' ? '正在校验输入，尚未发送保存' : phase==='SAVING' ? '正在等待保存回执，请勿重复提交' : receipt?.state==='SUCCEEDED' ? '已收到成功回执' : receipt?.state==='UNKNOWN' ? '保存结果待核对' : dirty ? '有未保存的修改' : loaded ? isEdit ? '当前显示已读取的资料' : '填写资料后保存' : '资料尚未读取' }}</span>
      <span v-if="loaded && isEdit" class="managed-form-version">ID {{ resourceId }} · 版本 {{ version ?? '未知' }}</span>
    </p>
    <el-alert v-if="permissionError" :title="permissionError" type="warning" show-icon :closable="false" />
    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />
    <el-button v-if="loadError && !permissionError && canReload" :disabled="phase!=='IDLE'" size="small" @click="$emit('reload')"><AppIcon name="Refresh" :size="14" />重新读取资料</el-button>
    <el-alert v-if="saveError" :title="saveError" :type="['UNKNOWN','SUCCEEDED'].includes(receipt?.state) ? 'warning' : 'error'" show-icon :closable="false" />
    <p v-if="validationError" class="managed-form-validation" role="alert">{{ validationError }}</p>
    <p v-if="lookupNotice" class="managed-form-lookup" role="status"><AppIcon name="Warning" :size="14" />{{ lookupNotice }}</p>
  </div>
</template>
<script setup>
defineProps({phase:String,dirty:Boolean,loaded:Boolean,isEdit:Boolean,resourceId:String,version:Number,receipt:Object,permissionError:String,loadError:String,saveError:String,validationError:String,lookupNotice:String,canReload:Boolean})
defineEmits(['reload'])
</script>
