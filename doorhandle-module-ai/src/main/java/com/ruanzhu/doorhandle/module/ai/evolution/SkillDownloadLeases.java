package com.ruanzhu.doorhandle.module.ai.evolution;

import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Unknown process exits retain their reservation. A worker keeps the claim returned at start. */
final class SkillDownloadLeases {
    static final long PACKAGE_BYTES=5242880;
    private final JdbcTemplate jdbc;private final SkillLinkStorage storage;private final SkillDownloadStore downloads;
    private final Map<String,SkillDownloadStore.Claim> claims=new ConcurrentHashMap<>();
    SkillDownloadLeases(JdbcTemplate jdbc,SkillLinkStorage storage){this.jdbc=jdbc;this.storage=storage;this.downloads=storage.downloads();}
    void schema(){JdbcOwnerLock.validateSchema(jdbc);downloads.schema();}
    void lock(long owner){JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.SKILL_DOWNLOAD,owner);}
    Map<String,Long> held(long owner){return downloads.held(owner);}
    long charged(long owner){return storage.chargedUsage(owner,held(owner));}
    void capacity(long owner,long quota){if(held(owner).size()>=2)throw fail(429,"请等待已有下载完成，或核对尚未确认退出的下载");if(Math.addExact(charged(owner),PACKAGE_BYTES)>quota)throw fail(413,"本人 Skill 存储配额不足 请清理未被版本引用的下载缓存");}
    void reserve(long owner,String id){downloads.reserve(owner,id);}
    boolean claim(long owner,String id,String instance){var claim=downloads.claim(owner,id,instance);if(claim==null)return false;claims.put(id,claim);return true;}
    void process(long owner,String id,String instance,Process process){downloads.process(owner,id,claim(id,instance),process);}
    void seal(long owner,String id,String instance){downloads.seal(owner,id,claim(id,instance));}
    void fail(long owner,String id,String instance,boolean exit,String code){downloads.failed(owner,id,claims.get(id),instance,exit,code);}
    void expire(long owner,String id){downloads.expire(owner,id);}
    void forget(String id){claims.remove(id);}
    private SkillDownloadStore.Claim claim(String id,String instance){var claim=claims.get(id);if(claim==null||!claim.worker().equals(instance))throw fail(409,"下载执行租约已变化");return claim;}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}
