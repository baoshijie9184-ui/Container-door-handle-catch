<template>
  <section v-if="notes" class="metadata-notes" aria-label="批次备注">
    <h4>批次备注</h4>
    <p>{{ notes }}</p>
  </section>
  <details v-if="images?.length" class="metadata-image-details" @toggle="imagesOpen=$event.currentTarget.open">
    <summary>图片资料（{{ images.length }} 张）</summary>
    <ul v-if="imagesOpen" class="metadata-images" tabindex="0" aria-label="图片与资料">
      <li v-for="image in images" :key="image.path">
        <strong>{{ image.path }}</strong>
        <p v-if="image.notes">{{ image.notes }}</p>
        <dl v-if="image.attributes && Object.keys(image.attributes).length">
          <div v-for="(value, label) in image.attributes" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
        </dl>
      </li>
    </ul>
  </details>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ notes: String, images: { type: Array, default: () => [] } })
const imagesOpen = ref(false)
</script>

<style scoped>
.metadata-notes,.metadata-image-details { margin-top:14px; border-top:1px solid var(--app-border); padding-top:10px; }
.metadata-notes h4 { margin:0 0 5px; font-size:14px; color:var(--app-text); }
.metadata-notes p,.metadata-images p { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
.metadata-image-details summary { cursor:pointer; font-weight:550; color:var(--app-text); }
.metadata-images { max-height:200px; overflow:auto; list-style:none; margin:8px 0 0; padding:0 12px; border-radius:8px; background:var(--app-surface-muted); }
.metadata-images li { padding:8px 0; overflow-wrap:anywhere; }
.metadata-images li + li { border-top:1px solid var(--app-border); }
.metadata-images dl { display:grid; gap:4px; margin:5px 0 0; }
.metadata-images dl div { display:flex; flex-wrap:wrap; gap:4px 10px; }
.metadata-images dt { color:var(--app-text-secondary); }
.metadata-images dd { margin:0; }
</style>
