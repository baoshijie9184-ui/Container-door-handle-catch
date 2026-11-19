package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.detection.ModelMaintenance;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ModelMaintenanceTest {
    @Test void countsTargetsAcrossAllSixClasses() {
        var rules=ModelMaintenance.from(Map.of("classCounts",Map.of("Normal",3,"Bent",2,"Deformed",2,"Rusty",0,"Missing",4,"Compromised",1))).groups();
        assertEquals(3L,rules.get(0).targetCount());
        assertEquals("维修",rules.get(1).label());
        assertEquals(2L,rules.get(1).targetCount());
        assertEquals("替换",rules.get(2).label());
        assertEquals(7L,rules.get(2).targetCount());
    }
    @Test void preservesUnknownCountsAndNeverTreatsMissingDataAsNormal() {
        var model=ModelMaintenance.from(Map.of("classCounts",Map.of("正常",0,"弯曲","2","Bent",2,"Missing",4,"other",2)));
        assertEquals(0L,model.groups().get(0).targetCount());
        assertEquals(2L,model.groups().get(1).targetCount());
        assertNull(model.groups().get(2).targetCount());
        assertEquals(java.util.List.of("other"),model.unmappedCategories());
        assertNull(ModelMaintenance.from(Map.of()).groups().get(0).targetCount());
    }
}
