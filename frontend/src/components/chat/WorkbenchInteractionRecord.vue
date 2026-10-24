<template>
  <div v-if="records.length" class="wb-interaction-record" :data-part="part">
    <section v-for="record in records" :key="record.key" :data-record="record.key">
      <h4><AppIcon :name="record.icon" :size="15" />{{ record.label }}<span v-if="record.values">{{ record.values.length }} 项</span></h4>
      <div class="wb-record-copy" :class="{'is-long':record.long}" :tabindex="record.long ? 0 : undefined" :role="record.long ? 'region' : undefined" :aria-label="record.long ? record.label+'完整内容，版本 '+(item.revision ?? '未记录')+'，可使用方向键滚动' : undefined">
        <ul v-if="record.values"><li v-for="(value,index) in record.values" :key="index">{{ value }}</li></ul>
        <p v-else>{{ record.text }}</p>
      </div>
      <p v-if="record.long" class="wb-record-reading-hint"><AppIcon name="Rank" :size="13" />完整内容保留在上方阅读区，可聚焦后用方向键滚动</p>
      <p v-if="record.note" class="wb-record-reading-hint">{{ record.note }}</p>
    </section>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { workbenchInteractionRecords } from '@/utils/workbenchRecordPresentation'
import '@/assets/workbench-interaction-record.css'
const props=defineProps({item:{type:Object,required:true},part:{type:String,default:'all'}})
const records=computed(()=>workbenchInteractionRecords(props.item).filter(record=>props.part==='body' ? record.key==='body' : props.part==='response' ? record.key!=='body' : true))
</script>
