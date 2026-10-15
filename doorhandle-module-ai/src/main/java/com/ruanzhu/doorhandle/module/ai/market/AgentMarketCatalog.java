package com.ruanzhu.doorhandle.module.ai.market;

import org.springframework.stereotype.Service;
import java.util.List;

/** 人工核实的外部资源目录；不下载资源、不连接 MCP，也不向模型授予工具。 */
@Service
public class AgentMarketCatalog {
    public enum Type { AGENT, MCP, SKILL }
    public enum Status { AVAILABLE, INTERFACE_ONLY, UNVERIFIED, OUT_OF_SCOPE }
    public record Link(String label, String url) {}
    public record Capability(Type type, Status status, String note, List<Link> links) {}
    public record Market(String id, String name, String region, String kind, String summary,
                         String homepage, String sourceUrl, List<Capability> capabilities) {}
    public record Catalog(String version, String verifiedOn, String integrationStatus, List<Market> markets) {}

    private static Capability available(Type type, String note, String label, String url) {
        return new Capability(type, Status.AVAILABLE, note, List.of(new Link(label, url)));
    }
    private static Capability unknown(Type type) {
        return new Capability(type, Status.UNVERIFIED, "尚未核实独立资源市场 不能据此认定平台没有此能力", List.of());
    }
    private static Capability outside(Type type) {
        return new Capability(type, Status.OUT_OF_SCOPE, "不属于当前目录的收录范围", List.of());
    }
    private static Market market(String id, String name, String region, String kind, String summary,
                                 String homepage, String source, Capability... capabilities) {
        return new Market(id, name, region, kind, summary, homepage, source, List.of(capabilities));
    }
    private static final Catalog CATALOG = new Catalog("2026-10-13.1", "2026-10-13", "DIRECTORY_ONLY", List.of(
        market("modelscope", "魔搭智能工坊", "国内", "资源广场", "智能工坊统一提供 Skills、MCPs、Agents 入口",
            "https://modelscope.cn/home", "https://modelscope.cn/home",
            available(Type.AGENT, "智能体目录 具体部署与接入方式以资源详情为准", "Agents 广场", "https://modelscope.cn/agents"),
            available(Type.MCP, "MCP 服务目录", "MCP 广场", "https://modelscope.cn/mcp"),
            available(Type.SKILL, "支持技能搜索、源码查看与下载", "Skills 技能中心", "https://modelscope.cn/skills")),
        market("bailian", "阿里云百炼", "国内", "托管平台", "支持创建与发布智能体 接入官方或自定义 MCP、Skill",
            "https://agent.console.aliyun.com/", "https://docs.agent.bailian.aliyun.com/en/flow-agent/applications/agent-app",
            available(Type.AGENT, "平台内创建、发布、API 调用 不等同于可下载的 AgentScope 模板", "Agent 开发说明", "https://docs.agent.bailian.aliyun.com/en/flow-agent/applications/agent-app"),
            available(Type.MCP, "One Key 服务与需开通服务 使用条件、收费以服务详情为准", "MCP 广场说明", "https://docs.agent.bailian.aliyun.com/zh/mcp/official-services"),
            available(Type.SKILL, "官方技能和自定义 ZIP 技能 运行环境需适配", "Skill 管理说明", "https://docs.agent.bailian.aliyun.com/en/skill")),
        market("aliyun-skills", "阿里云 Skills 门户", "国内", "产品技能门户", "阿里云产品相关技能与使用指导",
            "https://skills.aliyun.com/", "https://skills.aliyun.com/",
            unknown(Type.AGENT), unknown(Type.MCP), available(Type.SKILL, "云产品技能 安装前检查所需云账号权限", "Skills 门户", "https://skills.aliyun.com/")),
        market("aliyun-catalog", "阿里云 Agent 服务目录", "国内", "服务目录", "当前已核实 Skills 分类 其他类别留待进一步核实",
            "https://agentcatalog.aliyun.com/", "https://agentcatalog.aliyun.com/skills?orderBy=install",
            unknown(Type.AGENT), unknown(Type.MCP), available(Type.SKILL, "阿里云生态技能目录", "Skills 目录", "https://agentcatalog.aliyun.com/skills?orderBy=install")),
        market("mcp-so", "MCP.so", "国际", "聚合目录", "同时提供 MCP 服务器、Agent 产品与模板、Skill 目录",
            "https://mcp.so/", "https://mcp.so/",
            available(Type.AGENT, "产品与模板目录 不保证每个条目可直接下载运行", "Agent 目录", "https://mcp.so/agents"),
            available(Type.MCP, "第三方服务器目录 接入配置以原项目为准", "MCP 服务器", "https://mcp.so/servers"),
            available(Type.SKILL, "可复用 Agent 技能目录", "Skill 目录", "https://mcp.so/skills")),
        market("skills-sh", "Skills.sh", "国际", "技能目录", "Vercel 的技能搜索、排行榜与 CLI 安装生态",
            "https://skills.sh/", "https://github.com/vercel-labs/skills",
            unknown(Type.AGENT), unknown(Type.MCP), available(Type.SKILL, "面向多种 Agent 客户端的技能包", "Skill 广场", "https://skills.sh/")),
        market("skillhub", "腾讯 SkillHub", "国内", "技能广场", "中文技能广场 提供搜索、下载与版本查询开放 API",
            "https://www.skillhub.cn/", "https://github.com/Tencent/skillhub",
            unknown(Type.AGENT), unknown(Type.MCP), available(Type.SKILL, "可作为后续市场搜索与导入适配来源", "Skill 广场", "https://www.skillhub.cn/")),
        market("skillsmp", "SkillsMP", "国际", "技能聚合平台", "技能目录提供 REST API 和用于搜索技能的只读 MCP 接口",
            "https://skillsmp.com/", "https://skillsmp.com/developers",
            unknown(Type.AGENT), new Capability(Type.MCP, Status.INTERFACE_ONLY, "提供搜索技能的 MCP 接口 已核实接口不等同于 MCP 服务市场", List.of(new Link("MCP 接口说明", "https://skillsmp.com/developers"))),
            available(Type.SKILL, "分类与关键词搜索技能", "Skill 广场", "https://skillsmp.com/")),
        market("clawhub", "ClawHub", "国际", "技能与插件注册中心", "OpenClaw 的技能和插件生态 包内依赖需检查兼容性",
            "https://clawhub.ai/", "https://github.com/openclaw/clawhub",
            unknown(Type.AGENT), unknown(Type.MCP), available(Type.SKILL, "支持搜索、安装和版本管理 插件不保证兼容 AgentScope Java", "Skill 广场", "https://clawhub.ai/")),
        market("smithery", "Smithery", "国际", "MCP 服务平台", "提供 MCP 服务发现、连接和认证管理",
            "https://smithery.ai/", "https://smithery.ai/",
            unknown(Type.AGENT), available(Type.MCP, "连接服务的账号与调用条件以服务详情为准", "MCP 市场", "https://smithery.ai/"), unknown(Type.SKILL)),
        market("mcp-registry", "MCP 官方 Registry", "国际", "官方注册目录", "MCP 官方服务器元数据、版本与接入配置目录",
            "https://registry.modelcontextprotocol.io/", "https://github.com/modelcontextprotocol/registry",
            outside(Type.AGENT), available(Type.MCP, "发布者身份验证不等同于对全部工具行为的安全审核", "官方 MCP 目录", "https://registry.modelcontextprotocol.io/"), outside(Type.SKILL))
    ));

    public Catalog catalog() { return CATALOG; }
}
