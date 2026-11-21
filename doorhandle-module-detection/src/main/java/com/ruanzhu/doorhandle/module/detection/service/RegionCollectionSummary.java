package com.ruanzhu.doorhandle.module.detection.service;

import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Known regions and the counts that cannot be attributed to a registered place. */
public record RegionCollectionSummary(List<Region> regions, long unassignedImages, long unassignedTasks) {
    public record Region(String region, long imageCount, long taskCount) {}

    public static RegionCollectionSummary from(List<Map<String,Object>> groups) {
        Map<String,Region> regions = new HashMap<>();
        long unassignedImages = 0, unassignedTasks = 0;
        for (var row : groups) {
            String name = RegisteredRegionNames.lookup((String) row.get("region"));
            long images = ((Number) row.get("imageCount")).longValue();
            long tasks = ((Number) row.get("taskCount")).longValue();
            if (name == null) {
                unassignedImages += images;
                unassignedTasks += tasks;
            } else {
                regions.merge(name, new Region(name, images, tasks), (a,b) ->
                        new Region(name, a.imageCount + b.imageCount, a.taskCount + b.taskCount));
            }
        }
        var ranked = regions.values().stream().sorted(Comparator.comparingLong(Region::imageCount)
                .reversed().thenComparing(Region::region)).toList();
        return new RegionCollectionSummary(ranked, unassignedImages, unassignedTasks);
    }
}
