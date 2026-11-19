package com.ruanzhu.doorhandle.module.ai.model;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.fasterxml.jackson.annotation.JsonFormat;
import java.math.BigDecimal;

/** Prices are in native currency per million tokens. Cached tokens are a subset of input. */
final class ProviderMeter {
    static final BigDecimal MAX_LIMIT = new BigDecimal("1000000000000");
    record Rate(@JsonFormat(shape=JsonFormat.Shape.STRING) BigDecimal input,
                @JsonFormat(shape=JsonFormat.Shape.STRING) BigDecimal cached,
                @JsonFormat(shape=JsonFormat.Shape.STRING) BigDecimal output) {
        Rate {
            for (BigDecimal amount : new BigDecimal[]{input,cached,output}) {
                if (amount == null || amount.signum()<0 || amount.scale()>8 || amount.compareTo(new BigDecimal("100000000"))>0)
                    throw new BusinessException(400,"每百万 token 的单价须为非负数，最多 8 位小数");
            }
            if (input.max(cached).max(output).signum()==0) throw new BusinessException(400,"请核对模型单价");
        }
        BigDecimal hold(long tokens) {
            return input.max(cached).max(output).multiply(BigDecimal.valueOf(tokens)).movePointLeft(6);
        }
        BigDecimal cost(long in,long out,Long hit) {
            if (hit==null && input.compareTo(cached)!=0 && in>0) return null;
            long cachedTokens=hit==null?0:hit;
            if (in<0 || out<0 || cachedTokens<0 || cachedTokens>in) throw new IllegalArgumentException("Invalid provider usage");
            return input.multiply(BigDecimal.valueOf(in-cachedTokens)).add(cached.multiply(BigDecimal.valueOf(cachedTokens)))
                    .add(output.multiply(BigDecimal.valueOf(out))).movePointLeft(6);
        }
    }
    static String provider(String model) {
        ModelBudgetWorkflow.model(model);
        String prefix=model.substring(0,model.indexOf(':'));
        return prefix.equals("openai-official")?"openai":prefix;
    }
    static String unit(String provider) {
        return switch(provider) {
            case "openai" -> "USD";
            case "deepseek" -> "CNY";
            case "dashscope" -> "TOKEN";
            default -> throw new BusinessException(400,"未知厂家");
        };
    }
    static String pool(String model) {
        String vendor=provider(model);
        return vendor.equals("dashscope")?model:vendor;
    }
    static void amount(BigDecimal value,String unit) {
        if(value==null || value.signum()<0 || value.compareTo(MAX_LIMIT)>0
                || value.scale()>14 || (unit.equals("TOKEN") && value.stripTrailingZeros().scale()>0))
            throw new BusinessException(400,"额度必须是有效非负数，token 数须为整数");
    }
    private ProviderMeter() {}
}
