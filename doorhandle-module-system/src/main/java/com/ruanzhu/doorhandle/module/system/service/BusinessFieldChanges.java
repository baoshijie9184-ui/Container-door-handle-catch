package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant.Snapshot;
import com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory.Change;
import java.math.BigDecimal;
import java.util.*;

/** Compare raw domain allowlisted facts first, then apply irreversible display redaction. */
final class BusinessFieldChanges {
    private static final Map<String,String> LABELS=Map.ofEntries(
            Map.entry("name","姓名或部门名称"),Map.entry("employee_number","员工编号"),Map.entry("contact","联系方式"),
            Map.entry("gender","性别"),Map.entry("department_id","所属部门"),Map.entry("employee_type","人员岗位"),
            Map.entry("status","状态"),Map.entry("hire_date","入职日期"),Map.entry("device_code","设备编号"),
            Map.entry("device_type","设备类型"),Map.entry("model_name","模型或设备名称"),Map.entry("serial_number","序列号"),
            Map.entry("employee_id","关联员工编号"),Map.entry("employee_name","关联员工姓名（当时）"),
            Map.entry("department_name","所属部门名称（当时）"),
            Map.entry("device_id","关联设备编号"),Map.entry("device_model_name","关联设备型号（当时）"),Map.entry("last_maintenance_date","最近维护时间"),
            Map.entry("start_time","使用开始时间"),Map.entry("end_time","归还时间"),Map.entry("remarks","备注"),
            Map.entry("ack_operator","确认账号"),Map.entry("ack_remark","确认备注"),Map.entry("acknowledged_at","确认时间"),
            Map.entry("resolved_operator","解决账号"),Map.entry("resolved_remark","解决备注"),Map.entry("resolved_at","解决时间"),
            Map.entry("version","模型版本名称"),Map.entry("update_description","更新说明"),Map.entry("is_default","默认模型"),
            Map.entry("published_at","发布时间"),Map.entry("validation_status","验证状态"),Map.entry("mlops_status","模型治理状态"),
            Map.entry("evaluation_dataset","评估数据集"),Map.entry("precision_score","精确率"),Map.entry("recall_score","召回率"),
            Map.entry("map_score","mAP"),Map.entry("f1_score","F1"),Map.entry("training_image_count","训练图片数"),
            Map.entry("training_completed_at","训练完成时间"),Map.entry("evaluation_image_count","评估图片数"),
            Map.entry("no_detection_image_count","未检出图片数"),Map.entry("inference_fps","检测速度"),
            Map.entry("avg_inference_ms","平均推理时间"),Map.entry("compatibility_note","兼容性说明"),
            Map.entry("deployment_strategy","部署策略"),Map.entry("canary_percent","灰度比例"),Map.entry("ab_group","实验分组"),
            Map.entry("rollback_from_model_id","回滚来源模型"),Map.entry("model_path","模型文件"),
            Map.entry("claim_candidate_ids","领取候选账号 ID"));
    static List<Change> compare(Snapshot before,Snapshot after) {
        Map<String,Object> old=before==null?Map.of():before.fields(),next=after==null?Map.of():after.fields();
        var fields=new TreeSet<String>();fields.addAll(old.keySet());fields.addAll(next.keySet());
        var secrets=new HashSet<String>();var masks=new HashSet<String>();
        for(var snapshot:Arrays.asList(before,after))if(snapshot!=null){secrets.addAll(snapshot.secretFields());masks.addAll(snapshot.maskedFields());}
        var changes=new ArrayList<Change>();
        for(String field:fields){Object left=normalize(old.get(field)),right=normalize(next.get(field));
            if(old.containsKey(field)==next.containsKey(field)&&Objects.equals(left,right))continue;
            boolean secret=secrets.contains(field);boolean masked=masks.contains(field);
            changes.add(new Change(field,LABELS.getOrDefault(field,field),secret?"CHANGED":!old.containsKey(field)?"ADD":!next.containsKey(field)?"REMOVE":"REPLACE",
                    secret?null:masked?mask(left):left,secret?null:masked?mask(right):right,
                    secret?"SECRET":old.get(field) instanceof Number||next.get(field) instanceof Number?"NUMBER":"SCALAR",secret));
        }
        return List.copyOf(changes);
    }
    private static Object normalize(Object value){if(value instanceof Number number)return new BigDecimal(number.toString()).stripTrailingZeros();if(value instanceof java.time.temporal.TemporalAccessor)return value.toString();return value;}
    private static Object mask(Object value){if(value==null)return null;String text=value.toString();return text.isEmpty()?"":text.length()<=4?"****":"***"+text.substring(text.length()-4);}
}
