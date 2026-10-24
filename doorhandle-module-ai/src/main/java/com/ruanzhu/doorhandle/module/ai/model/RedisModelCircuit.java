package com.ruanzhu.doorhandle.module.ai.model;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** One Redis hash per configuration revision and model; no prompt or credential data. */
final class RedisModelCircuit extends ModelCircuit {
    private final StringRedisTemplate redis;
    private final String key;
    private final int threshold;
    private final long cooldownMs, quotaCooldownMs, probeLeaseMs;

    static final class Unavailable extends IllegalStateException {
        Unavailable(){super("模型协调服务不可用，本次不会额外调用其他供应商");}
    }

    // Server time, generation fencing and probe ownership are tested atomically by Redis.
    private static final DefaultRedisScript<List> SCRIPT=new DefaultRedisScript<>("""
        redis.replicate_commands()
        local key=KEYS[1]
        local clock=redis.call('TIME')
        local now=tonumber(clock[1])*1000+math.floor(tonumber(clock[2])/1000)
        local gen=tonumber(redis.call('HGET',key,'generation') or '0')
        local opened=redis.call('HGET',key,'open')=='1'
        local untilTime=tonumber(redis.call('HGET',key,'until') or '0')
        local lease=tonumber(redis.call('HGET',key,'probeUntil') or '0')
        local operation=ARGV[1]
        if operation=='ACQUIRE' then
            redis.call('HSET',key,'generation',gen)
            redis.call('EXPIRE',key,604800)
            if not opened then return {gen,0,''} end
            if untilTime>now or lease>now then return {-1,0,''} end
            gen=redis.call('HINCRBY',key,'generation',1)
            redis.call('HSET',key,'probeUntil',now+tonumber(ARGV[4]),'probeToken',ARGV[3])
            return {gen,1,ARGV[3]}
        end
        if operation=='HEALTH' then
            local state='CLOSED'
            if opened then
                if lease>now then state='HALF_OPEN'
                elseif untilTime>now then state='OPEN'
                else state='PROBE_READY' end
            end
            return {state,redis.call('HGET',key,'failure') or '',math.max(0,math.ceil((untilTime-now)/1000))}
        end
        if gen~=tonumber(ARGV[2]) then return {0} end
        if ARGV[3]~='' and redis.call('HGET',key,'probeToken')~=ARGV[3] then return {0} end
        if operation=='SUCCESS' then
            redis.call('HSET',key,'failures',0,'open',0,'probeUntil',0,'probeToken','','failure','')
            if ARGV[3]~='' then redis.call('HINCRBY',key,'generation',1) end
        elseif operation=='FAILURE' then
            local failures=redis.call('HINCRBY',key,'failures',1)
            redis.call('HSET',key,'failure',ARGV[4])
            if ARGV[3]~='' or failures>=tonumber(ARGV[5]) or ARGV[4]=='QUOTA' or ARGV[4]=='AUTH' then
                redis.call('HSET',key,'open',1,'until',now+tonumber(ARGV[6]),'probeUntil',0,'probeToken','')
                redis.call('HINCRBY',key,'generation',1)
            end
        elseif operation=='RELEASE' and ARGV[3]~='' then
            redis.call('HSET',key,'probeUntil',0,'probeToken','')
        end
        return {1}
        """,List.class);

    RedisModelCircuit(StringRedisTemplate redis,long revision,String modelId,int threshold,
                      Duration cooldown,Duration quotaCooldown,Duration requestTimeout){
        super(threshold,cooldown,quotaCooldown);
        this.redis=Objects.requireNonNull(redis);
        this.threshold=threshold;this.cooldownMs=cooldown.toMillis();this.quotaCooldownMs=quotaCooldown.toMillis();
        this.probeLeaseMs=Math.addExact(requestTimeout.toMillis(),30000);
        try{
            String digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(modelId.getBytes(StandardCharsets.UTF_8)));
            this.key="doorhandlecatch:agent:model-circuit:{"+revision+":"+digest+"}";
        }catch(Exception error){throw new IllegalArgumentException("模型协调编号无效");}
    }
    private List execute(String... args){
        try{List result=redis.execute(SCRIPT,List.of(key),(Object[])args);if(result==null||result.isEmpty())throw new Unavailable();return result;}
        catch(RuntimeException ignored){throw new Unavailable();}
    }
    private long number(Object value){try{return Long.parseLong(value.toString());}catch(RuntimeException ignored){throw new Unavailable();}}
    @Override Permit acquire(){
        var result=execute("ACQUIRE","0",UUID.randomUUID().toString(),Long.toString(probeLeaseMs));
        if(result.size()!=3)throw new Unavailable();
        long generation=number(result.get(0));
        return generation<0?null:new Permit(generation,number(result.get(1))==1,result.get(2).toString());
    }
    @Override void success(Permit permit){execute("SUCCESS",Long.toString(permit.generation()),permit.token());}
    @Override void failure(Permit permit,ModelFailureClassifier.Failure reason){
        long delay=reason==ModelFailureClassifier.Failure.QUOTA||reason==ModelFailureClassifier.Failure.AUTH?quotaCooldownMs:cooldownMs;
        execute("FAILURE",Long.toString(permit.generation()),permit.token(),reason.name(),Integer.toString(threshold),Long.toString(delay));
    }
    @Override void release(Permit permit){if(permit.probe())execute("RELEASE",Long.toString(permit.generation()),permit.token());}
    @Override Health health(){
        var result=execute("HEALTH");if(result.size()!=3)throw new Unavailable();
        String failure=result.get(1).toString();return new Health(result.get(0).toString(),failure.isEmpty()?null:failure,number(result.get(2)));
    }
}
