package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;

/** The caller supplies a new local schema with the real compact baseline and 007 already applied. */
@EnabledIfSystemProperty(named="doorhandle.provider.fixture",matches=".+")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ProviderBudgetMySqlTest {
    static final String A="dashscope:qwen-plus", B="dashscope:qwen-flash";
    static final String GPT="openai-official:gpt-6.2-sol", GPT2="openai-official:gpt-6.2-astra";
    final ThreadLocal<Long> current=ThreadLocal.withInitial(()->3L);
    JdbcTemplate jdbc; TransactionTemplate tx; ProviderBudgetService nativeBudgets; ModelBudgetService budgets;
    String key(){return UUID.randomUUID().toString();}
    @BeforeAll void setup() throws Exception {
        Properties settings=new Properties();
        try(var in=Files.newInputStream(Path.of(System.getProperty("doorhandle.provider.fixture")))){settings.load(in);}
        String url=settings.getProperty("url");
        assertTrue(url.matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]{1,5}/doorhandle_provider_test_[a-f0-9]{12}\\?.*"));
        var ds=new DriverManagerDataSource(url,settings.getProperty("user"),settings.getProperty("password"));
        jdbc=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));
        assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM users",Integer.class));
        jdbc.update("INSERT INTO users(id,username,password,role) VALUES(3,'boss','fixture','SUPERVISOR'),(4,'alice','fixture','INSPECTOR'),(5,'bob','fixture','INSPECTOR')");
        var identities=new BusinessUserDirectory(){
            public Identity current(long id,String user){return new Identity(id,user,id==3);}
            public Identity authenticated(){return switch(current.get().intValue()){case 3->current(3,"boss");case 4->current(4,"alice");default->current(5,"bob");};}
            public Identity lockCurrent(long id,String name){jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE",Long.class,id);return current(id,name);}
        };
        var json=new ObjectMapper().findAndRegisterModules().setSerializationInclusion(JsonInclude.Include.NON_NULL);
        nativeBudgets=new ProviderBudgetService(jdbc,identities,json);budgets=new ModelBudgetService(jdbc,identities,json);
        budgets.setProviderBudgets(nativeBudgets);
    }
    BigDecimal n(String s){return s==null?null:new BigDecimal(s);}
    ProviderBudgetService.Policy allocation(String kind,String model,Long employee,String limit,String opening,long version){
        return new ProviderBudgetService.Policy(kind,model,employee,n(limit),n(opening),null,null,null,version,key());
    }
    void configure(ProviderBudgetService.Policy p){tx.executeWithoutResult(s->nativeBudgets.configure(p));}
    void pool(String model,String cap,String opening){configure(allocation("NATIVE_POOL",model,null,cap,opening,0));}
    void member(String model,long id,String cap){configure(allocation("NATIVE_MEMBER",model,id,cap,null,0));}
    void rate(String model,String i,String c,String o,long v){
        configure(new ProviderBudgetService.Policy("NATIVE_RATE",model,null,null,null,n(i),n(c),n(o),v,key()));
    }
    ModelBudgetService.Ticket start(String model,long ceiling){
        long id=current.get();
        var actor=new AgentActor(id,id==3?"boss":id==4?"alice":"bob",id==3?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        return tx.execute(t->budgets.started(new ModelBudgetContext(actor,"fixture-run"),key(),key(),model,ceiling,"TEXT_UTF8_ESTIMATE_V1"));
    }
    void finish(ModelBudgetService.Ticket t,long in,long out,Long cache){
        var values=new HashMap<String,Object>(Map.of("modelId",t.modelId(),"status","COMPLETED","inputTokens",in,"outputTokens",out));
        if(cache!=null)values.put("cachedTokens",cache);
        budgets.finished(t,values);
    }
    ProviderBudgetService.View view(long who){return nativeBudgets.view(who,Long.MAX_VALUE,false);}
    ProviderBudgetService.Account account(long id,String kind,String key){
        return view(id).accounts().stream().filter(a->a.kind().equals(kind)&&a.key().equals(key)).findFirst().orElseThrow();
    }
    @Test void companyPoolsEmployeeLimitsAndConcurrentReservations() throws Exception {
        current.set(3L);
        pool(A,"1000000","0");pool(B,"1000000","0");pool(GPT,"93","0.03");
        member(A,4,"1000");member(GPT,4,"2");rate(GPT,"10","2","20",0);rate(GPT2,"10","2","20",0);
        current.set(4L);
        assertThrows(ModelBudgetService.Exhausted.class,()->start(B,10));
        assertThrows(BusinessException.class,()->view(5));
        assertThrows(BusinessException.class,()->nativeBudgets.employees("",0));
        assertThrows(BusinessException.class,()->member(B,4,"1000"));
        var t=start(A,1000);
        assertThrows(ModelBudgetService.Exhausted.class,()->start(A,1));
        finish(t,300,100,100L);finish(t,300,100,100L);
        assertEquals("600",account(4,"NATIVE_MEMBER",A).available());
        assertEquals("400",account(4,"NATIVE_MEMBER",A).spent());
        var money=start(GPT,5000);
        current.set(3L);
        rate(GPT,"200","20","200",1);
        finish(money,1000,500,250L);
        assertEquals("92.952",account(4,"NATIVE_POOL","openai").available());
        assertEquals("1.982",account(4,"NATIVE_MEMBER","openai").available());
        assertEquals("999600",account(4,"NATIVE_POOL",A).available());
        assertEquals("1000000",account(4,"NATIVE_POOL",B).available());
        current.set(4L);
        var gpt2=start(GPT2,1000);budgets.cancelUnsent(gpt2);
        assertEquals("1.982",account(4,"NATIVE_MEMBER","openai").available());
        current.set(5L);assertThrows(ModelBudgetService.Exhausted.class,()->start(A,1));
        current.set(3L);member(B,5,"100");
        var threads=Executors.newFixedThreadPool(2);
        try {
            var ready=new CountDownLatch(2);var go=new CountDownLatch(1);
            Callable<Boolean> call=()->{current.set(5L);ready.countDown();go.await();try{start(B,80);return true;}catch(ModelBudgetService.Exhausted denied){return false;}};
            var x=threads.submit(call);var y=threads.submit(call);assertTrue(ready.await(5,TimeUnit.SECONDS));go.countDown();
            assertNotEquals(x.get(10,TimeUnit.SECONDS),y.get(10,TimeUnit.SECONDS));
        }finally{threads.shutdownNow();}
        assertEquals("80",account(5,"NATIVE_MEMBER",B).reserved());
        assertThrows(BusinessException.class,()->configure(allocation("NATIVE_MEMBER",B,5L,"50",null,1)));
        assertThrows(BusinessException.class,()->configure(allocation("NATIVE_MEMBER",B,5L,"500",null,0)));
        var topup=allocation("NATIVE_MEMBER",B,5L,"300",null,1);
        configure(topup);configure(topup);
        assertEquals("220",account(5,"NATIVE_MEMBER",B).available());
        assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM llm_usage WHERE native_command=?",Integer.class,topup.requestId()));
        member(GPT,3,"0.05");
        var own=start(GPT2,1000);
        finish(own,100,100,0L);
        assertEquals("0.047",account(3,"NATIVE_MEMBER","openai").available());
        assertEquals("1.982",account(4,"NATIVE_MEMBER","openai").available());
        assertEquals("92.949",account(3,"NATIVE_POOL","openai").available());
    }
    @Test void supervisorAllocatesAndConsumesOwnNativeLimitWithoutAnApplication(){
        current.set(3L);String model="dashscope:supervisor-fixture";
        pool(model,"1000","0");
        jdbc.update("INSERT INTO llm_quota(scope_type,owner_user_id,model_id,period_key,total_tokens,created_at,updated_at) VALUES('USER',3,?,'TOTAL',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",model);
        assertThrows(ModelBudgetService.Exhausted.class,()->start(model,1));
        assertEquals("0",account(3,"NATIVE_POOL",model).reserved());
        var self=allocation("NATIVE_MEMBER",model,3L,"100",null,0);
        configure(self);configure(self);
        pool(model+"-other","1000","0");
        assertThrows(ModelBudgetService.Exhausted.class,()->start(model+"-other",1));
        var attempt=start(model,100);
        assertThrows(ModelBudgetService.Exhausted.class,()->start(model,1));
        assertEquals("100",account(3,"NATIVE_MEMBER",model).reserved());
        assertThrows(BusinessException.class,()->configure(allocation("NATIVE_MEMBER",model,3L,"99",null,1)));
        finish(attempt,40,20,null);
        finish(attempt,40,20,null);
        assertEquals("40",account(3,"NATIVE_MEMBER",model).available());
        assertEquals("60",account(3,"NATIVE_MEMBER",model).spent());
        assertEquals("940",account(3,"NATIVE_POOL",model).available());
        assertEquals(0L,jdbc.queryForObject("SELECT spent_tokens FROM llm_quota WHERE scope_type='USER' AND owner_user_id=3 AND model_id=? AND period_key='TOTAL'",Long.class,model));
        assertThrows(ModelBudgetService.Exhausted.class,()->start(model,41));
        var canceled=start(model,40);budgets.cancelUnsent(canceled);
        assertEquals("40",account(3,"NATIVE_MEMBER",model).available());
        configure(allocation("NATIVE_MEMBER",model,3L,"2000",null,1));
        assertThrows(ModelBudgetService.Exhausted.class,()->start(model,941));
        tx.executeWithoutResult(status->{
            jdbc.update("UPDATE users SET role='SUPERVISOR' WHERE id=5");
            assertThrows(BusinessException.class,()->nativeBudgets.configure(allocation("NATIVE_MEMBER",model,5L,"100",null,0)));
            status.setRollbackOnly();
        });
        current.set(4L);
        assertThrows(BusinessException.class,()->view(3));
        assertThrows(BusinessException.class,()->member(model,4,"100"));
    }
    @Test void uncertainDeepSeekCostRetainsHoldsUntilAnAuditedReview(){
        current.set(3L);String ds="deepseek:deepseek-flash";pool(ds,"100","0");member(ds,4,"5");rate(ds,"1","0.1","2",0);
        current.set(4L);var t=start(ds,1000);finish(t,80,20,null);
        assertEquals("0.002",account(4,"NATIVE_MEMBER","deepseek").reserved());
        var pending=view(4).usage().stream().filter(a->a.attempt()==t.attemptId()).findFirst().orElseThrow();
        assertEquals(80L,pending.inputTokens());assertEquals(20L,pending.outputTokens());
        assertNull(pending.cost());assertEquals("NEEDS_REVIEW",pending.status());
        var review=new ProviderBudgetService.Review(80L,20L,40L,n("0.000084"),"test-invoice-123",key());
        assertThrows(BusinessException.class,()->tx.executeWithoutResult(s->nativeBudgets.review(t.attemptId(),review)));
        current.set(3L);
        tx.executeWithoutResult(s->nativeBudgets.review(t.attemptId(),review));
        tx.executeWithoutResult(s->nativeBudgets.review(t.attemptId(),review));
        assertEquals("4.999916",account(4,"NATIVE_MEMBER","deepseek").available());
        current.set(4L);var timed=start(ds,1000);finish(timed,80,20,40L);finish(timed,80,20,40L);
        var completeTokens=view(4).usage().stream().filter(a->a.attempt()==timed.attemptId()).findFirst().orElseThrow();
        assertEquals(40L,completeTokens.cachedTokens());assertEquals("NEEDS_REVIEW",completeTokens.status());
        assertNull(completeTokens.cost());
        current.set(3L);
        var conflicting=new ProviderBudgetService.Review(80L,20L,30L,n("0.000042"),"bad-cache",key());
        assertThrows(BusinessException.class,()->tx.executeWithoutResult(s->nativeBudgets.review(timed.attemptId(),conflicting)));
        var invoice=new ProviderBudgetService.Review(80L,20L,null,n("0.000042"),"confirmed-offpeak",key());
        tx.executeWithoutResult(s->nativeBudgets.review(timed.attemptId(),invoice));
        tx.executeWithoutResult(s->nativeBudgets.review(timed.attemptId(),invoice));
        assertEquals("0.000126",account(4,"NATIVE_MEMBER","deepseek").spent());
        assertEquals("BILL",view(4).usage().stream().filter(a->a.attempt()==t.attemptId()).findFirst().orElseThrow().basis());
        current.set(4L);
        var unknown=start(ds,1000);budgets.finished(unknown,Map.of("modelId",ds,"status","FAILED"));
        current.set(3L);
        var clear=new ProviderBudgetService.Review(0L,0L,null,ZERO,"supplier-confirmed-no-charge",key());
        tx.executeWithoutResult(s->nativeBudgets.review(unknown.attemptId(),clear));
        assertEquals("0",account(4,"NATIVE_MEMBER","deepseek").reserved());
        assertEquals("4.999874",account(4,"NATIVE_MEMBER","deepseek").available());
        member(ds,3,"1");
        var own=start(ds,1000);finish(own,80,20,40L);
        assertEquals("0.002",account(3,"NATIVE_MEMBER","deepseek").reserved());
        var ownInvoice=new ProviderBudgetService.Review(80L,20L,40L,n("0.000084"),"self-invoice",key());
        tx.executeWithoutResult(s->nativeBudgets.review(own.attemptId(),ownInvoice));
        assertEquals("0.999916",account(3,"NATIVE_MEMBER","deepseek").available());
        assertEquals("4.999874",account(4,"NATIVE_MEMBER","deepseek").available());
    }
    private static final BigDecimal ZERO=BigDecimal.ZERO;
}
