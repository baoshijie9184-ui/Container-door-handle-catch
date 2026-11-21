package com.ruanzhu.doorhandle.module.detection.service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class RegionCollectionSummaryTest {
    @Test void matchesWholePlaceNamesAndValidParentage() {
        assertEquals("北京市", RegisteredRegionNames.lookup(" 北京 "));
        assertEquals("浦东新区", RegisteredRegionNames.lookup("上海市/浦东新区"));
        assertEquals("南山区", RegisteredRegionNames.lookup("南山区"));
        assertEquals("深圳市南山区", RegisteredRegionNames.lookup("广东省_深圳市_南山区"));
        assertEquals("朝阳区", RegisteredRegionNames.lookup("朝阳区"));
        assertEquals("长春市朝阳区", RegisteredRegionNames.lookup("吉林省长春市朝阳区"));
        assertEquals("新疆维吾尔自治区", RegisteredRegionNames.lookup("新疆"));
        for (String value : List.of("吉林", "上海市海淀区", "返工区", "设备A", "单图检测", "未提供", "北京100张实测", "unknown-region", "  "))
            assertNull(RegisteredRegionNames.lookup(value), value);
    }

    @Test void totalsAccountForUnregisteredLocationsWithoutAddingThemToTheRanking() {
        var summary = RegionCollectionSummary.from(List.of(group("天津",7,2), group("天津市",3,1),
                group("海淀区",8,1), group("北京100张实测",100,1), group(null,6,2), group("未提供",0,1)));
        assertEquals(List.of(new RegionCollectionSummary.Region("天津市",10,3),
                new RegionCollectionSummary.Region("海淀区",8,1)), summary.regions());
        assertEquals(106, summary.unassignedImages());
        assertEquals(4, summary.unassignedTasks());
        assertTrue(RegionCollectionSummary.from(List.of(group("单图检测",1,1))).regions().isEmpty());
        assertEquals(new RegionCollectionSummary(List.of(),0,0), RegionCollectionSummary.from(List.of()));
    }

    private Map<String,Object> group(String region, long images, long tasks) {
        var row = new HashMap<String,Object>();
        row.put("region",region);
        row.put("imageCount",images);
        row.put("taskCount",tasks);
        return row;
    }
}
