<template>
  <figure class="handle-graphic">
    <svg viewBox="0 0 440 320" role="img" aria-label="集装箱门把手盖检测区域示意，不代表实际检测结果">
      <rect x="44" y="14" width="350" height="280" rx="12" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2" />
      <path d="M219 15v278" stroke="#cbd5e1" stroke-width="3" />
      <g stroke="#e2e8f0" stroke-width="7" stroke-linecap="round">
        <path d="M74 40v226m31-226v226m31-226v226m165-226v226m31-226v226m31-226v226" />
      </g>
      <g stroke="#64748b" fill="#f1f5f9" stroke-width="3">
        <path d="M176 38v233m85-233v233" /><rect x="166" y="54" width="20" height="16" rx="3" /><rect x="251" y="54" width="20" height="16" rx="3" />
        <rect x="166" y="237" width="20" height="16" rx="3" /><rect x="251" y="237" width="20" height="16" rx="3" />
        <path d="M176 157h29v13h-29m85-13h-29v13h29" stroke-linejoin="round" />
      </g>
      <rect x="150" y="139" width="141" height="48" rx="7" fill="#2563eb0b" stroke="#2563eb" stroke-dasharray="5 5" />
      <g stroke="#2563eb" stroke-width="3" fill="none"><path d="M150 151v-12h12m117 0h12v12m0 24v12h-12m-117 0h-12v-12" /></g>
      <path d="M292 163h33l24-27" fill="none" stroke="#2563eb" stroke-width="1.5" />
      <rect x="298" y="103" width="124" height="31" rx="7" fill="white" stroke="#dbe7fb" />
      <text x="310" y="123" fill="#1d4ed8" font-size="12" font-family="sans-serif">门把手盖检测区域</text>
      <path d="M44 306h350" stroke="#cbd5e1" />
      <path d="M44 302v8m350-8v8" stroke="#cbd5e1" />
    </svg>
    <figcaption>围绕原图、检测结果与人工结论建立质量记录</figcaption>
  </figure>
</template>
<style scoped>
.handle-graphic { max-width: 470px; margin: 28px 0 20px; }
.handle-graphic svg { width: 100%; height: auto; }
.handle-graphic figcaption { color: var(--app-text-muted); text-align: center; font-size: 11px; margin-top: 8px; }
</style>
