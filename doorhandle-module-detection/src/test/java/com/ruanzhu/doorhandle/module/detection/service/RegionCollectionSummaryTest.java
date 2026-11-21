package com.ruanzhu.doorhandle.module.detection.service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class RegionCollectionSummaryTest {
    @Test void matchesWholePlaceNamesAndValidParentage() {
        for (String city : RegisteredRegionNames.COLLECTION_CITIES) {
            assertEquals(city, RegisteredRegionNames.lookup(city));
            assertEquals(city, RegisteredRegionNames.lookup(city.substring(0, city.length() - 1)));
        }
        assertEquals("上海市", RegisteredRegionNames.lookup(" 上海市/浦东新区 "));
        assertEquals("武汉市", RegisteredRegionNames.lookup("湖北省_武汉市_洪山区"));
        assertEquals("天津市", RegisteredRegionNames.lookup("天津市和平区"));
        for (String value : List.of("和平区", "北京", "朝阳区", "广东省深圳市南山区", "通州区",
                "上海市海淀区", "返工区", "设备A", "单图检测", "未提供", "北京100张实测", "  "))
            assertNull(RegisteredRegionNames.lookup(value), value);
    }

    @Test void totalsAccountForUnregisteredLocationsWithoutAddingThemToTheRanking() {
        var summary = RegionCollectionSummary.from(List.of(group("天津",7,2), group("天津市",3,1),
                group("天津市和平区",4,1), group("武汉市",8,1), group("海淀区",8,1), group("北京100张实测",100,1), group(null,6,2), group("未提供",0,1)));
        assertEquals(List.of(new RegionCollectionSummary.Region("天津市",14,4),
                new RegionCollectionSummary.Region("武汉市",8,1)), summary.regions());
        assertEquals(114, summary.unassignedImages());
        assertEquals(5, summary.unassignedTasks());
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
