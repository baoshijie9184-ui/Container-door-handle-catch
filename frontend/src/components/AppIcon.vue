<template>
  <el-icon :size="size" aria-hidden="true"><component :is="icons[name] || Files" /></el-icon>
</template>
<script setup>
import {
  Files, HomeFilled, DataAnalysis, Picture, Monitor, User, Tickets, Document,
  DocumentCopy, DocumentChecked, Upload, Search, Connection, Key, CircleCheck,
  ChatDotRound, Collection, Operation, Plus, Refresh, ArrowLeft, ArrowRight,
  ArrowUp, ArrowDown, Close, Menu, Fold, Expand, Download, Delete, Edit, Filter, Lock, Warning, Clock,
  Compass, Cpu, TopRight, Rank, MagicStick, List, CircleClose, RefreshLeft
} from '@element-plus/icons-vue'
defineProps({ name: { type: String, default: 'Files' }, size: { type: [Number, String], default: 18 } })
const icons = {
  Files, HomeFilled, DataAnalysis, Picture, Monitor, User, Tickets, Document,
  DocumentCopy, DocumentChecked, Upload, Search, Connection, Key, CircleCheck,
  ChatDotRound, Collection, Operation, Plus, Refresh, ArrowLeft, ArrowRight,
  ArrowUp, ArrowDown, Close, Menu, Fold, Expand, Download, Delete, Edit, Filter, Lock, Warning, Clock,
  Compass, Cpu, TopRight, Rank, MagicStick, List, CircleClose, RefreshLeft
}
</script>
