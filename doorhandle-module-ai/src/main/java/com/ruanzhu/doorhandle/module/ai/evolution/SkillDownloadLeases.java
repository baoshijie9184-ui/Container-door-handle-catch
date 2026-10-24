package com.ruanzhu.doorhandle.module.ai.evolution;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;

/** All state transitions run inside the caller's transaction and account lock. Unknown exits retain the full reservation. */
final class SkillDownloadLeases {
    static final long PACKAGE_BYTES=5242880;
    private final JdbcTemplate jdbc;private final SkillLinkStorage storage;
    SkillDownloadLeases(JdbcTemplate jdbc,SkillLinkStorage storage){this.jdbc=jdbc;this.storage=storage;}
    void schema(){jdbc.queryForList("SELECT owner_user_id FROM agent_skill_download_owner WHERE 1=0");jdbc.queryForList("SELECT worker_instance,exit_verified,lease_expires_at FROM agent_skill_download_lease WHERE 1=0");jdbc.queryForList("SELECT action FROM agent_skill_download_event WHERE 1=0");}
    void lock(long owner){if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("下载配额需要数据库事务");jdbc.update("INSERT INTO agent_skill_download_owner(owner_user_id) VALUES(?) ON DUPLICATE KEY UPDATE owner_user_id=VALUES(owner_user_id)",owner);jdbc.queryForObject("SELECT owner_user_id FROM agent_skill_download_owner WHERE owner_user_id=? FOR UPDATE",Long.class,owner);}
    Map<String,Long> held(long owner){
        var held=new LinkedHashMap<String,Long>();
        for(var row:jdbc.queryForList("SELECT download_id,reserved_bytes FROM agent_skill_download_lease WHERE owner_user_id=? AND status IN ('RESERVED','RUNNING','NEEDS_REVIEW')",owner))held.put((String)row.get("download_id"),((Number)row.get("reserved_bytes")).longValue());
        for(String id:jdbc.queryForList("SELECT d.download_id FROM agent_skill_download d LEFT JOIN agent_skill_download_lease l ON l.download_id=d.download_id WHERE d.owner_user_id=? AND d.status IN ('DOWNLOADING','NEEDS_REVIEW') AND l.download_id IS NULL",String.class,owner))held.put(id,PACKAGE_BYTES);
        return held;
    }
    long charged(long owner){return storage.chargedUsage(owner,held(owner));}
    void capacity(long owner,long quota){if(held(owner).size()>=2)throw fail(429,"请等待已有下载完成，或核对尚未确认退出的下载");if(Math.addExact(charged(owner),PACKAGE_BYTES)>quota)throw fail(413,"本人 Skill 存储配额不足 请清理未被版本引用的下载缓存");}
    void reserve(long owner,String id){jdbc.update("INSERT INTO agent_skill_download_lease(download_id,owner_user_id,status,reserved_bytes,lease_expires_at) VALUES(?,?,'RESERVED',?,TIMESTAMPADD(MINUTE,5,CURRENT_TIMESTAMP))",id,owner,PACKAGE_BYTES);event(owner,id,"QUOTA_RESERVED");}
    boolean claim(long owner,String id,String instance){boolean claimed=jdbc.update("UPDATE agent_skill_download_lease SET status='RUNNING',worker_instance=?,lease_expires_at=TIMESTAMPADD(MINUTE,5,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='RESERVED' AND lease_expires_at>CURRENT_TIMESTAMP",instance,id,owner)==1;if(claimed)event(owner,id,"DOWNLOAD_CLAIMED");return claimed;}
    void process(long owner,String id,String instance,Process process){if(jdbc.update("UPDATE agent_skill_download_lease SET process_pid=?,process_started_at=?,updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='RUNNING' AND worker_instance=? AND lease_expires_at>CURRENT_TIMESTAMP",process.pid(),process.info().startInstant().map(Object::toString).orElse(null),id,owner,instance)!=1)throw fail(409,"下载执行租约已变化");event(owner,id,"PROCESS_REGISTERED");}
    void seal(long owner,String id,String instance){if(jdbc.update("UPDATE agent_skill_download_lease SET status='SEALED',exit_verified=TRUE,reserved_bytes=0,updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='RUNNING' AND worker_instance=? AND lease_expires_at>CURRENT_TIMESTAMP",id,owner,instance)!=1)throw fail(409,"下载租约已变化，不能导入此结果");event(owner,id,"PACKAGE_SEALED");}
    void fail(long owner,String id,String instance,boolean exit,String code){
        var rows=jdbc.queryForList("SELECT status,worker_instance FROM agent_skill_download_lease WHERE owner_user_id=? AND download_id=? FOR UPDATE",owner,id);
        if(rows.isEmpty())return;var row=rows.get(0);String phase=(String)row.get("status");
        if(Set.of("SEALED","RELEASED").contains(phase)||!phase.equals("RESERVED")&&!Objects.equals(instance,row.get("worker_instance")))return;
        jdbc.update("UPDATE agent_skill_download SET status=?,error_code=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND download_id=? AND status IN ('DOWNLOADING','DOWNLOADED','NEEDS_REVIEW')",exit?"ERROR":"NEEDS_REVIEW",code,owner,id);
        jdbc.update("UPDATE agent_skill_download_lease SET status=?,exit_verified=?,reserved_bytes=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND download_id=?",exit?"RELEASED":"NEEDS_REVIEW",exit,exit?0:PACKAGE_BYTES,owner,id);
        event(owner,id,exit?"EXIT_CONFIRMED":"EXIT_UNVERIFIED");
    }
    void expire(long owner,String id){
        var rows=jdbc.queryForList("SELECT l.status FROM agent_skill_download_lease l WHERE l.owner_user_id=? AND l.download_id=? AND l.status IN ('RESERVED','RUNNING') AND l.lease_expires_at<CURRENT_TIMESTAMP FOR UPDATE",owner,id);
        if(rows.isEmpty())return;boolean unstarted=rows.get(0).get("status").equals("RESERVED");
        jdbc.update("UPDATE agent_skill_download_lease SET status=?,exit_verified=?,reserved_bytes=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND download_id=?",unstarted?"RELEASED":"NEEDS_REVIEW",unstarted,unstarted?0:PACKAGE_BYTES,owner,id);
        jdbc.update("UPDATE agent_skill_download SET status=?,error_code=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND download_id=? AND status='DOWNLOADING'",unstarted?"ERROR":"NEEDS_REVIEW",unstarted?"DOWNLOAD_NOT_STARTED":"DOWNLOAD_EXIT_UNVERIFIED",owner,id);
        event(owner,id,unstarted?"UNSTARTED_EXPIRED":"RESTART_NEEDS_REVIEW");
    }
    private void event(long owner,String id,String action){jdbc.update("INSERT INTO agent_skill_download_event(owner_user_id,download_id,action,status) SELECT owner_user_id,download_id,?,status FROM agent_skill_download_lease WHERE owner_user_id=? AND download_id=?",action,owner,id);}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}
