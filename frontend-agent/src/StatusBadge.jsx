import React from 'react';
import { CircleCheck, Clock, TriangleAlert, FileText, FileCheck, Files, Image, Upload, Download, Monitor, UserRound, Search, LockKeyhole, RefreshCw, Network, ClipboardList, Layers, Pencil, MessageSquare, Copy, X, Settings2, ChartNoAxesCombined } from 'lucide-react';
import { statusPresentation } from '../../frontend/src/utils/statusPresentation';

// Match the shared semantic icon names; warning does not always mean waiting.
const icons = {
  CircleCheck, Clock, Warning:TriangleAlert, Document:FileText, DocumentChecked:FileCheck,
  Files, Picture:Image, Upload, Download, Monitor, User:UserRound, Search, Lock:LockKeyhole,
  Refresh:RefreshCw, Connection:Network, Tickets:ClipboardList, Collection:Layers, Edit:Pencil,
  ChatDotRound:MessageSquare, DocumentCopy:Copy, Close:X, Operation:Settings2, DataAnalysis:ChartNoAxesCombined,
};
export default function StatusBadge({ domain, code, label }) {
  const status = statusPresentation(domain, code, label);
  const Icon = icons[status.icon] || FileText;
  return <span className="business-status" data-tone={status.tone} title={status.label + (status.code ? ' · ' + status.code : '')}><Icon size={13} aria-hidden="true" /><span>{status.label}</span></span>;
}
