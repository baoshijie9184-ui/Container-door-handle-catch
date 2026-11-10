package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots.Mapping;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.util.*;

@Component
public class ModelMutationParticipant implements BusinessMutationParticipant,BusinessResourceAccess {
    private static final Mapping MODEL=new Mapping("DETECTION_MODEL","model_management","model_id","row_version",List.of(
            "model_name","version","update_description","status","is_default","published_at","validation_status","validation_message","mlops_status",
            "evaluation_dataset","precision_score","recall_score","map_score","training_image_count","training_completed_at",
            "evaluation_image_count","no_detection_image_count","inference_fps","f1_score","avg_inference_ms","compatibility_note",
            "deployment_strategy","canary_percent","ab_group","rollback_from_model_id","model_path"),Set.of(),Set.of("model_path","validation_message"));
    private static final Set<String> ACTIONS=Set.of("UPLOAD","updateModel","deleteModel","publishModel","setDefaultModel","DISABLE","ARCHIVE","VALIDATE",
            "saveModelInfo","updateModelInfo","RECORD_EVALUATION","CONFIGURE_ROLLOUT","deleteModelInfoByModelId");
    private static final String[] INPUT={"modelId","rowVersion","modelName","version","modelPath","updateDescription","status","isDefault",
            "uploadTime","evaluationDataset","precisionScore","recallScore","mapScore","trainingImageCount","trainingCompletedAt",
            "evaluationImageCount","noDetectionImageCount","inferenceFps","f1Score","avgInferenceMs","compatibilityNote","deploymentStrategy","canaryPercent","abGroup","rollbackFromModelId"};
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;private final JdbcMutationSnapshots snapshots;
    public ModelMutationParticipant(JdbcTemplate jdbc,BusinessUserDirectory users){this.jdbc=jdbc;this.users=users;snapshots=new JdbcMutationSnapshots(jdbc);}
    public boolean supports(String domain,String action){return "DETECTION_MODEL".equals(domain)&&ACTIONS.contains(action);}
    public boolean creates(String action){return Set.of("UPLOAD","saveModelInfo").contains(action);}
    public String resourceId(String domain,String action,Object[] args,Object result){Object selected="UPLOAD".equals(action)?result:args[0];if(selected==null)return null;if(selected instanceof Number)return selected.toString();Object id=JdbcMutationSnapshots.properties(selected,"modelId").get("modelId");return id==null?null:id.toString();}
    public Snapshot capture(AgentActor actor,String domain,String action,String id,boolean lock){require(actor);return snapshots.capture(MODEL,id,lock);}
    public void prepare(AgentActor actor,String domain,String action,String id,Object[] arguments){
        if(!users.lockCurrent(actor.userId(),actor.username()).supervisor())throw new SecurityException("模型管理权限已撤销");
        if("setDefaultModel".equals(action)){
            // Default selection updates multiple models; lock the complete candidate set in primary key order.
            var ids=jdbc.queryForList("SELECT model_id FROM model_management ORDER BY model_id FOR UPDATE",Integer.class);
            if(ids.size()>10000)throw new IllegalArgumentException("模型目录超过单次切换上限");
        }
    }
    public Snapshot advanceVersion(Snapshot before,Snapshot after){return snapshots.advance(MODEL,before,after);}
    public Object digestInput(String action,Object[] args){
        if("UPLOAD".equals(action)){var file=(ModelUploadFiles.Prepared)args[0];return Arrays.asList(file.sha256(),file.size(),file.actorUserId(),args[1],args[2],args[3]);}
        if(Set.of("saveModelInfo","updateModelInfo","updateModel").contains(action))return JdbcMutationSnapshots.properties(args[0],INPUT);
        if("RECORD_EVALUATION".equals(action))return Arrays.asList(args[0],JdbcMutationSnapshots.properties(args[1],INPUT));
        return Arrays.asList(args);
    }
    public boolean mayRead(AgentActor actor,String scope,String domain,String type,String id){
        if(!"ENTERPRISE".equals(scope)||!"DETECTION_MODEL".equals(domain)||!"DETECTION_MODEL".equals(type))return false;
        // Detection model catalogue is enterprise-readable; current authenticated identity is still required.
        try{users.current(actor.userId(),actor.username());return true;}catch(SecurityException denied){return false;}
    }
    private void require(AgentActor actor){if(!users.current(actor.userId(),actor.username()).supervisor())throw new SecurityException("模型管理权限已撤销");}
    public List<Snapshot> related(AgentActor actor,String domain,String action,String id,Object[] arguments,List<Snapshot> previous,boolean lock){
        if(!"setDefaultModel".equals(action))return List.of();require(actor);var ids=new TreeSet<String>();for(var item:previous)ids.add(item.resourceId());
        for(Integer other:jdbc.queryForList("SELECT model_id FROM model_management WHERE is_default=1 ORDER BY model_id",Integer.class))if(!other.toString().equals(id))ids.add(other.toString());
        if(ids.size()>100)throw new IllegalStateException("默认模型数量异常，请先核对");var result=new ArrayList<Snapshot>();for(String other:ids){var item=snapshots.capture(MODEL,other,lock);if(item!=null)result.add(item);}return result;
    }
}
