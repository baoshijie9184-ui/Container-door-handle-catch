package com.ruanzhu.doorhandle.module.ai.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** 草稿写入必须绑定实际运行；原运行行锁与草稿业务共用单体事务。 */
public class AgentReportGateway {
    public static final String POLICY="report-own-draft-v1";
    private final QualityReportAgentApi reports;
    private final AgentJournal journal;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final ObjectMapper canonical;
    public AgentReportGateway(QualityReportAgentApi reports,AgentJournal journal,JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json){
        this.reports=reports;this.journal=journal;this.jdbc=jdbc;this.transaction=new TransactionTemplate(manager);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        transaction.setTimeout(15);
        canonical=json.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }
    public boolean draftsEnabled(){return journal.enabled();}
    public QualityReportAgentApi.Page list(AgentActor actor,int page,int size,String status,String keyword){return reports.list(actor,page,size,status,keyword);}
    public QualityReportAgentApi.Detail get(AgentActor actor,String reportId){return reports.get(actor,reportId);}
    public QualityReportAgentApi.Detail write(AgentActor actor,String runId,String callId,String tool,Map<String,Object> args){
        if(!draftsEnabled()||runId==null||!runId.matches("[A-Za-z0-9_:.-]{1,128}")||callId==null||!callId.matches("[A-Za-z0-9_:.-]{1,160}"))
            throw new SecurityException("草稿保存缺少持久运行上下文");
        if(!Set.of("create_report_draft","edit_report_draft").contains(tool))throw new SecurityException("报告写工具未授权");
        String requestId=digest(Map.of("runId",runId,"tool",tool,"arguments",args));
        return transaction.execute(status->{
            var rows=jdbc.queryForList("SELECT user_id,main_agent,status,lease_expires_at FROM agent_run WHERE run_id=? FOR UPDATE",runId);
            if(rows.isEmpty())throw new SecurityException("运行不存在");
            var run=rows.get(0);
            if(((Number)run.get("user_id")).longValue()!=actor.userId()||!com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog.mainId(actor).equals(run.get("main_agent"))
                    ||!"RUNNING".equals(run.get("status")))throw new SecurityException("运行身份或状态不允许草稿写入");
            Long live=jdbc.queryForObject("SELECT COUNT(*) FROM agent_run WHERE run_id=? AND lease_expires_at>CURRENT_TIMESTAMP",Long.class,runId);
            if(live!=1)throw new SecurityException("运行租约已失效");
            var origin=new QualityReportAgentApi.Origin(requestId,runId,callId,tool);
            return "create_report_draft".equals(tool)?reports.createDraft(actor,new QualityReportAgentApi.Draft((String)args.get("taskId"),(String)args.get("title"),(String)args.get("narrative")),origin)
                    :reports.editDraft(actor,new QualityReportAgentApi.Edit((String)args.get("reportId"),((Number)args.get("expectedVersion")).intValue(),(String)args.get("title"),(String)args.get("narrative")),origin);
        });
    }
    private String digest(Object value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical.writeValueAsBytes(value)));}catch(Exception error){throw new IllegalStateException("报告请求摘要计算失败",error);}}
}
