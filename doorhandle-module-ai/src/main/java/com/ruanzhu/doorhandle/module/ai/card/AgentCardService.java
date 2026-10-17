package com.ruanzhu.doorhandle.module.ai.card;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import java.time.LocalDateTime;
import java.util.*;

/** 刷新卡片只调用业务读门面，重新检查账号角色及每个对象的当前访问范围。 */
@Service
public class AgentCardService {
    private final DetectionAgentReadApi detection;
    private final ObjectProvider<QualityReportAgentApi> reports;
    private final BusinessUserDirectory users;
    private final ResourceAgentReadApi resources;
    private final ModelAgentReadApi models;
    public AgentCardService(DetectionAgentReadApi detection,ObjectProvider<QualityReportAgentApi> reports,BusinessUserDirectory users,
                            ResourceAgentReadApi resources,ModelAgentReadApi models) {
        this.detection=detection;this.reports=reports;this.users=users;this.resources=resources;this.models=models;
    }
    public List<AgentCards.View> resolve(AgentActor authenticated,List<AgentCards.Reference> refs) {
        if(refs==null||refs.size()>8)throw new IllegalArgumentException("卡片数量超出范围");
        var current=users.current(authenticated.userId(),authenticated.username());
        var actor=new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        return refs.stream().map(ref->resolveOne(actor,ref)).toList();
    }
    private AgentCards.View resolveOne(AgentActor actor,AgentCards.Reference ref) {
        boolean allowed=com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog.specialists(actor,false,true,true)
                .stream().anyMatch(def->def.tools().contains(ref.tool()));
        if(!allowed)return view(ref,"UNAVAILABLE",List.of(),Map.of(),null,null,null,"此卡片已不可用 请重新查询");
        if(ref.type().equals("METRICS")) {
            try {
                var data=detection.metrics(actor,ref.days());var counts=new LinkedHashMap<String,Object>();
                for(String key:List.of("taskCount","imageCount","processedImageCount","defectCount")) {
                    Object value=data.counts().get(key);
                    if(value instanceof Number n&&Double.isFinite(n.doubleValue())&&n.doubleValue()>=0)counts.put(key,value);
                }
                return view(ref,"OK",List.of(),counts,Objects.toString(data.from(),null),Objects.toString(data.to(),null),data.scope(),"按任务创建时间重新统计 缺陷数量不等于缺陷图片数");
            } catch(RuntimeException ignored) {return view(ref,"UNAVAILABLE",List.of(),Map.of(),null,null,null,"统计暂不可用 请稍后刷新");}
        }
        var items=new ArrayList<Object>();boolean removed=false,failed=false;
        for(String id:ref.ids()) {
            try {
                if(ref.type().equals("TASKS"))items.add(detection.task(actor,id));
                else if(ref.type().equals("DEVICES"))items.add(Objects.requireNonNull(resources.device(actor,Long.parseLong(id))));
                else if(ref.type().equals("DEVICE_ALERTS"))items.add(Objects.requireNonNull(resources.alert(actor,Long.parseLong(id))));
                else if(ref.type().equals("MODELS"))items.add(Objects.requireNonNull(models.model(actor,Integer.parseInt(id))));
                else if(ref.type().equals("MODEL_OPERATIONS"))items.add(Objects.requireNonNull(models.operations(actor,Integer.parseInt(id))));
                else {
                    var api=reports.getIfAvailable();if(api==null)throw new IllegalStateException();
                    items.add(api.get(actor,id).report()); // 明确排除正文、依据全文和审批凭证。
                }
            } catch(SecurityException|org.springframework.security.access.AccessDeniedException denied) {removed=true;}
            catch(BusinessException error) {if(Set.of(403,404).contains(error.getCode()))removed=true;else failed=true;}
            catch(RuntimeException error) {failed=true;}
        }
        String status=failed?"UNAVAILABLE":removed?"PARTIAL":"OK";
        String message=failed?"部分数据暂不可用 请稍后刷新":removed?"部分记录已不存在或当前无权访问":ref.ids().isEmpty()?"本次查询没有记录":"仅展示本次工具结果中的前五条 当前状态以业务页面为准";
        return view(ref,status,items,Map.of(),null,null,actor.supervisor()?"SINGLE_ENTERPRISE":"OWNED_OR_ASSIGNED",message);
    }
    private AgentCards.View view(AgentCards.Reference ref,String status,List<?> items,Map<String,Object> metrics,String from,String to,String scope,String message) {
        return new AgentCards.View(ref.type(),ref.tool(),status,List.copyOf(items),metrics,from,to,scope,message,LocalDateTime.now().toString());
    }
}
