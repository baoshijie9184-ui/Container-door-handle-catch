package com.ruanzhu.doorhandle.module.ai.workbench;

import com.ruanzhu.doorhandle.module.ai.context.ChildProvenanceReader;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import java.util.Optional;

/** Identity-only lookup without a workbench owner lock after a context lock. */
@Component
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public final class WorkbenchChildProvenanceReader implements ChildProvenanceReader {
    private final WorkbenchStore store;
    public WorkbenchChildProvenanceReader(WorkbenchStore store){this.store=store;}
    @Override public Optional<ChildProvenance> find(long ownerUserId,String sessionId,String itemId){return store.childProvenance(ownerUserId,sessionId,itemId);}
}
