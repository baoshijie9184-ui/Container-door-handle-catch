package com.ruanzhu.doorhandle.module.system.service;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.security.LoginSessionAccess;
import com.ruanzhu.doorhandle.module.system.dto.LoginResponse;
import com.ruanzhu.doorhandle.module.system.security.LoginSessionProperties;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.CredentialsExpiredException;
import org.springframework.security.authentication.DisabledException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Objects;
import org.springframework.context.ApplicationEventPublisher;
import com.ruanzhu.doorhandle.contracts.security.LoginSessionRevoked;
import com.ruanzhu.doorhandle.contracts.security.AccountAccessChanged;

/** Bounded durable sessions. Refresh keeps one fixed, hashed credential for this session's fixed lifetime.
 * Concurrent refreshes therefore cannot install an older refresh credential; logout serializes on the same row. */
@Service
public class LoginSessionService implements LoginSessionAccess {
    public record Payload(int version,long userId,String username,String role,String accountContext,String refreshDigest) {}
    private record Row(long revision,String state,Payload payload,Instant expiresAt) {}
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final LoginEligibilityService eligibility;
    private final LoginSessionProperties properties;
    private final JwtUtil jwt;
    private final ObjectMapper json;
    private final ApplicationEventPublisher events;
    private final SecureRandom random=new SecureRandom();
    public LoginSessionService(JdbcTemplate jdbc,PlatformTransactionManager manager,LoginEligibilityService eligibility,LoginSessionProperties properties,JwtUtil jwt,ObjectMapper json,ApplicationEventPublisher events){
        this.jdbc=jdbc;transaction=new TransactionTemplate(manager);transaction.setTimeout(10);
        this.eligibility=eligibility;this.properties=properties;this.jwt=jwt;this.events=events;
        this.json=json.copy().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES,DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    }
    public boolean enabled(){return properties.isEnabled();}
    public LoginEligibilityService.Eligible currentAccount(long id,String username){return eligibility.requireCurrent(id,username);}
    @PostConstruct public void validateSchema(){
        if(!enabled())return;
        jdbc.queryForList("SELECT id,enabled,account_version FROM users WHERE 1=0");
        Integer guards=jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='runtime_state' AND constraint_name='ck_runtime_login_session' AND constraint_type='CHECK'",Integer.class);
        if(guards==null||guards!=1)throw new IllegalStateException("LOGIN_SESSION schema contract is required before activation");
    }
    public LoginResponse login(long id,String username){
        var account=eligibility.requireCurrent(id,username);
        Instant created=Instant.now().truncatedTo(ChronoUnit.SECONDS),expires=created.plusSeconds(jwt.refreshExpirationSeconds());
        String sid=secret(),context=secret(),digest=digest(sid);
        String refresh=jwt.generateSessionRefresh(id,username,sid,created,expires);
        var payload=new Payload(1,id,username,account.role(),context,digest(refresh));
        transaction.executeWithoutResult(status->{
            var current=eligibility.lockCurrent(id,username);
            if(!current.role().equals(account.role()))throw invalid();
            jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,window_started_at,window_ends_at,payload_version,payload_json,created_at,updated_at) VALUES('LOGIN_SESSION',?,?,0,'ACTIVE',?,?,1,?,?,?)",
                    id,digest,utc(created),utc(expires),encode(payload),utc(created),utc(created));
        });
        return response(account,sid,refresh,context,expires);
    }
    @Override public Session requireActive(long userId,String username,String sessionDigest){
        if(!enabled())throw invalid();
        Row row=read(userId,sessionDigest,false);validate(row,userId,username);
        LoginEligibilityService.Eligible account;
        try {account=eligibility.requireCurrent(userId,username);}
        catch(DisabledException failure){revokeAll(userId);throw failure;}
        if(!account.role().equals(row.payload.role())){revokeAll(userId);throw invalid();}
        return new Session(userId,username,account.role(),sessionDigest,row.payload.accountContext(),row.expiresAt);
    }
    public LoginResponse refresh(String refresh,String expectedContext){
        if(!jwt.validateToken(refresh)||!jwt.isRefreshToken(refresh))throw invalid();
        Long id=jwt.getUserIdFromToken(refresh);String sid=jwt.getSessionId(refresh),username=jwt.getUsernameFromToken(refresh);
        if(id==null||sid==null)throw invalid();
        // Check current account before the transaction so a rejection persists the revocation.
        requireActive(id,username,digest(sid));
        return transaction.execute(status->{
            // Account -> session is the same lock order used when disabling an account.
            var account=eligibility.lockCurrent(id,username);
            Row row=read(id,digest(sid),true);validate(row,id,username);context(row.payload.accountContext(),expectedContext);
            if(!constant(row.payload.refreshDigest(),digest(refresh)))throw invalid();
            if(!account.role().equals(row.payload.role()))throw invalid();
            if(jdbc.update("UPDATE runtime_state SET revision=revision+1,updated_at=? WHERE namespace='LOGIN_SESSION' AND owner_id=? AND scope_key=? AND state_code='ACTIVE' AND revision=?",
                    utc(Instant.now()),id,digest(sid),row.revision)!=1)throw invalid();
            return response(account,sid,refresh,row.payload.accountContext(),row.expiresAt);
        });
    }
    public void logout(String access,String refresh,String expectedContext){
        String token=jwt.validateToken(access)&&jwt.isAccessToken(access)?access:refresh;
        if(token==null||!jwt.validateToken(token)||(!jwt.isAccessToken(token)&&!jwt.isRefreshToken(token)))throw invalid();
        Long id=jwt.getUserIdFromToken(token);String sid=jwt.getSessionId(token),username=jwt.getUsernameFromToken(token);
        if(id==null||sid==null)throw invalid();
        transaction.executeWithoutResult(status->{
            Row row=read(id,digest(sid),true);
            if(row==null||!Objects.equals(username,row.payload.username()))throw invalid();
            context(row.payload.accountContext(),expectedContext);
            if(jwt.isRefreshToken(token)&&!constant(row.payload.refreshDigest(),digest(token)))throw invalid();
            jdbc.update("UPDATE runtime_state SET state_code='REVOKED',revision=revision+1,updated_at=? WHERE namespace='LOGIN_SESSION' AND owner_id=? AND scope_key=? AND state_code='ACTIVE'",utc(Instant.now()),id,digest(sid));
            events.publishEvent(new LoginSessionRevoked(id,digest(sid)));
        });
    }
    public void revokeAll(long id){
        transaction.executeWithoutResult(status->{
            jdbc.update("UPDATE runtime_state SET state_code='REVOKED',revision=revision+1,updated_at=? WHERE namespace='LOGIN_SESSION' AND owner_id=? AND state_code='ACTIVE'",utc(Instant.now()),id);
            events.publishEvent(new AccountAccessChanged(id));
        });
    }
    @org.springframework.transaction.event.TransactionalEventListener(phase=org.springframework.transaction.event.TransactionPhase.BEFORE_COMMIT)
    public void personnelChanged(com.ruanzhu.doorhandle.contracts.security.LoginEligibilityChanged event){
        if(enabled())revokeAll(event.userId());
    }
    @org.springframework.transaction.event.TransactionalEventListener(phase=org.springframework.transaction.event.TransactionPhase.BEFORE_COMMIT)
    public void employeeChanged(com.ruanzhu.doorhandle.contracts.security.EmployeeLoginEligibilityChanged event){
        if(enabled())for(long id:jdbc.queryForList("SELECT id FROM users WHERE employee_id=? ORDER BY id",Long.class,event.employeeId()))revokeAll(id);
    }
    private Row read(long id,String digest,boolean lock){
        if(id<=0||digest==null||!digest.matches("[a-f0-9]{64}"))throw invalid();
        var rows=jdbc.query("SELECT revision,state_code,payload_version,payload_json,window_ends_at FROM runtime_state WHERE namespace='LOGIN_SESSION' AND owner_id=? AND scope_key=?"+(lock?" FOR UPDATE":""),(rs,n)->{
            String raw=rs.getString("payload_json");
            if(rs.getInt("payload_version")!=1||raw==null||raw.length()>4096)throw invalid();
            try{return new Row(rs.getLong("revision"),rs.getString("state_code"),json.readValue(raw,Payload.class),rs.getObject("window_ends_at",LocalDateTime.class).toInstant(ZoneOffset.UTC));}
            catch(Exception failure){throw invalid();}
        },id,digest);
        return rows.isEmpty()?null:rows.get(0);
    }
    private static void validate(Row row,long id,String username){
        if(row==null||!"ACTIVE".equals(row.state)||!row.expiresAt.isAfter(Instant.now())||row.payload.version()!=1||row.payload.userId()!=id||
                !Objects.equals(username,row.payload.username())||!("SUPERVISOR".equals(row.payload.role())||"INSPECTOR".equals(row.payload.role()))||row.payload.accountContext()==null||!row.payload.accountContext().matches("[A-Za-z0-9_-]{43}")||
                row.payload.refreshDigest()==null||!row.payload.refreshDigest().matches("[a-f0-9]{64}"))throw invalid();
    }
    public static void context(String actual,String supplied){
        if(actual==null||supplied==null||!constant(actual,supplied))throw new AccountContextChangedException();
    }
    private LoginResponse response(LoginEligibilityService.Eligible account,String sid,String refresh,String context,Instant expires){
        var user=account.user();var result=new LoginResponse();result.setUserId(user.getId());result.setUsername(user.getUsername());result.setRole(account.role());result.setAccountContext(context);
        result.setToken(jwt.generateSessionAccess(user.getId(),user.getUsername(),sid,expires));result.setAccessExpiresAt(jwt.getExpiresAt(result.getToken()));
        result.setRefreshToken(refresh);result.setRefreshExpiresAt(expires);result.setEmail(user.getEmail());result.setPhone(user.getPhone());return result;
    }
    private String secret(){byte[] bytes=new byte[32];random.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);}
    public static String digest(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
    public static String legacyAccountContext(long id,String username){return digest("doorhandle-legacy-account-context:v1\u0000"+id+"\u0000"+username);}
    /** Expiry keeps the bounded metadata as evidence; never deletes a business row. */
    @org.springframework.scheduling.annotation.Scheduled(fixedDelayString="${collaboration.sessions.expiry-scan-ms:60000}")
    public void expireSessions(){
        if(!enabled())return;
        transaction.executeWithoutResult(status->{
            var expired=jdbc.queryForList("SELECT owner_id,scope_key FROM runtime_state WHERE namespace='LOGIN_SESSION' AND state_code='ACTIVE' AND window_ends_at<=? ORDER BY window_ends_at,owner_id,scope_key LIMIT 500 FOR UPDATE",utc(Instant.now()));
            for(var row:expired){long id=((Number)row.get("owner_id")).longValue();String digest=(String)row.get("scope_key");
                jdbc.update("UPDATE runtime_state SET state_code='REVOKED',revision=revision+1,updated_at=? WHERE namespace='LOGIN_SESSION' AND owner_id=? AND scope_key=? AND state_code='ACTIVE'",utc(Instant.now()),id,digest);
                events.publishEvent(new LoginSessionRevoked(id,digest));
            }
        });
    }
    private static boolean constant(String first,String second){return first!=null&&second!=null&&MessageDigest.isEqual(first.getBytes(StandardCharsets.UTF_8),second.getBytes(StandardCharsets.UTF_8));}
    private static LocalDateTime utc(Instant value){return LocalDateTime.ofInstant(value,ZoneOffset.UTC);}
    private String encode(Payload value){try{return json.writeValueAsString(value);}catch(Exception failure){throw new IllegalStateException("Login session metadata encoding failed",failure);}}
    private static CredentialsExpiredException invalid(){return new CredentialsExpiredException("登录会话无效或已撤销，请重新登录");}
}
