package com.ruanzhu.doorhandle.module.ai.mcp;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.Map;

/** One SQL fence per immutable image. Readers remain enforced when the cleanup UI is disabled. */
public final class FetchImageRegistry {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final boolean required;
    public FetchImageRegistry(JdbcTemplate jdbc,PlatformTransactionManager manager,boolean required){this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.tx.setTimeout(10);this.required=required;}
    public boolean available(){
        Integer count=jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='agent_fetch_image'",Integer.class);
        if(count==null||count==0){if(required)throw new IllegalStateException("MCP_IMAGE_MIGRATION_REQUIRED");return false;}return true;
    }
    public void schema(){if(available()){jdbc.queryForList("SELECT image_id,state,revision,cleanup_request,runner_pool_id,archive_sha256,image_absent FROM agent_fetch_image WHERE 1=0");jdbc.queryForList("SELECT image_id FROM agent_mcp_execution WHERE 1=0");}}
    public Map<String,Object> lock(String image){
        if(image==null||!image.matches("sha256:[a-f0-9]{64}"))throw new IllegalArgumentException("MCP_IMAGE_INVALID");
        jdbc.update("INSERT IGNORE INTO agent_fetch_image(image_id,state) VALUES(?,'ACTIVE')",image);
        return jdbc.queryForMap("SELECT * FROM agent_fetch_image WHERE image_id=? FOR UPDATE",image);
    }
    public void usable(String image){
        if(image==null)return;
        if(!available())return; // Never cache absence across a later controlled migration.
        tx.executeWithoutResult(status->{if(!"ACTIVE".equals(lock(image).get("state")))throw new ResponseStatusException(HttpStatus.CONFLICT,"此固定 Fetch 镜像已进入回收流程 不能建立新的引用或执行");});
    }
}
