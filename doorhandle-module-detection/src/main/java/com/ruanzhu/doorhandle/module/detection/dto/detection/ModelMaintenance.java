package com.ruanzhu.doorhandle.module.detection.dto.detection;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Derived from model target counts. Human review and release decisions remain separate records. */
public record ModelMaintenance(List<Group> groups, List<String> unmappedCategories) {
    public record Group(String code, String label, Long targetCount, List<Category> categories) {}
    public record Category(String code, String label, Long targetCount) {}

    private record ModelClass(String code, String label) {
        boolean matches(Object key) {
            return key instanceof String name && (code.equalsIgnoreCase(name.trim()) || label.equals(name.trim()));
        }

        Category read(Map<?,?> counts) {
            Long count = null;
            for (var item : counts.entrySet()) {
                if (!matches(item.getKey())) continue;
                Long next = targetCount(item.getValue());
                if (next == null || (count != null && !count.equals(next))) return new Category(code,label,null);
                count = next;
            }
            return new Category(code,label,count);
        }
    }

    private enum Rule {
        NONE("无需处理", new ModelClass("Normal","正常")),
        REPAIR("维修", new ModelClass("Bent","弯曲")),
        REPLACE("替换", new ModelClass("Deformed","形变"), new ModelClass("Rusty","锈蚀"),
            new ModelClass("Missing","缺失"), new ModelClass("Compromised","结构损伤"));

        final String label;
        final List<ModelClass> classes;
        Rule(String label, ModelClass... classes) {
            this.label = label;
            this.classes = List.of(classes);
        }
    }

    public static ModelMaintenance from(Map<String,Object> statistics) {
        Map<?,?> counts = statistics != null && statistics.get("classCounts") instanceof Map<?,?> values ? values : Map.of();
        var groups = new ArrayList<Group>();
        for (Rule rule : Rule.values()) {
            var categories = rule.classes.stream().map(type -> type.read(counts)).toList();
            Long total = categories.stream().anyMatch(type -> type.targetCount() == null) ? null
                : categories.stream().mapToLong(Category::targetCount).sum();
            groups.add(new Group(rule.name(),rule.label,total,categories));
        }
        var unmapped = counts.keySet().stream().filter(String.class::isInstance).map(String.class::cast)
            .filter(key -> groups.stream().flatMap(group -> group.categories().stream())
                .noneMatch(type -> type.code().equalsIgnoreCase(key.trim()) || type.label().equals(key.trim())))
            .toList();
        return new ModelMaintenance(groups,unmapped);
    }

    private static Long targetCount(Object value) {
        if (!(value instanceof Number || value instanceof String)) return null;
        try {
            long n = new BigDecimal(value.toString().trim()).longValueExact();
            // All six counts are image-model targets. Bound each component before summation.
            return n >= 0 && n <= Integer.MAX_VALUE ? n : null;
        } catch (ArithmeticException | NumberFormatException invalid) {
            return null;
        }
    }
}
