package com.ruanzhu.doorhandle.contracts.agent;

import java.text.Normalizer;
import java.util.Optional;
import java.util.regex.Pattern;

/** Rejects explicit requests before they reach a model. Tool and resource authorization also apply at execution. */
public enum AgentRequestRestriction {
    PROTECTED_CREDENTIALS("请求读取受保护的凭据",
            "当前请求涉及读取密码、密码哈希、密钥或访问令牌。Agent 无权读取这些凭据，人工确认也不能授予访问权限。"),
    TERMINAL_EXECUTION("请求执行终端命令",
            "当前请求涉及使用终端或执行系统命令。Agent 无权使用终端或执行这些命令，人工确认也不能授予执行权限。");

    private static final int MATCH_FLAGS = Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE;
    private static final String CREDENTIAL = "(?:密码(?!策略|规则|要求|格式|强度)|口令|密[钥鑰](?!类型|格式)|访问令牌|认证令牌|数据库连接串|"
            + "凭据(?!策略|规则|管理|格式)|"
            + "\\b(?:passwords?|passphrases?|api[ _-]*keys?|secret[ _-]*keys?|access[ _-]*tokens?|"
            + "refresh[ _-]*tokens?|private[ _-]*keys?|credentials?)\\b)";
    private static final String READ = "(?:读取|查看|查询|列出|显示|获取|提取|导出|打印|告诉我|发给我|给我|是什么|是多少|"
            + "\\b(?:read|show|reveal|retrieve|get|list|export|print|give me|what (?:is|are))\\b)";
    private static final Pattern CREDENTIAL_REQUEST = Pattern.compile(
            READ + ".{0,60}" + CREDENTIAL + "|" + CREDENTIAL + ".{0,40}" + READ, MATCH_FLAGS);
    private static final Pattern RESET_INSTRUCTIONS = Pattern.compile(
            "(?:如何|怎么|怎样)\\s*(?:修改|重置|找回|更换|更新)|\\bhow (?:to|do i) (?:reset|change|rotate|revoke)\\b", MATCH_FLAGS);

    private static final String SHELL = "(?:终端|命令行|\\b(?:terminal|shell|bash|zsh|powershell|cmd(?:\\.exe)?)\\b)";
    private static final String RUN = "(?:执行|运行|启动|\\b(?:execute|run|launch)\\b)";
    private static final Pattern TERMINAL_REQUEST = Pattern.compile(
            "(?:在|用|通过|借助|打开|进入|使用).{0,14}" + SHELL + ".{0,36}" + RUN
            + "|" + RUN + ".{0,22}(?:终端命令|系统命令|命令行命令|" + SHELL + "\\s*(?:命令|脚本|commands?|scripts?))"
            + "|" + RUN + ".{0,70}\\b(?:in|on|via|through|using)\\b.{0,16}" + SHELL
            + "|\\b(?:use|open|start)\\b.{0,16}" + SHELL + ".{0,24}" + RUN
            + "|(?:打开|进入|启动|\\bopen\\b).{0,12}" + SHELL
            + "|(?:调用|使用|\\b(?:invoke|call|use)\\b)\\s*`?\\b(?:exec_command|execute_command|run_command)\\b", MATCH_FLAGS);
    private static final Pattern TERMINAL_EXPLANATION = Pattern.compile(
            "^(?:请\\s*)?(?:解释|说明|介绍|如何|怎么|怎样|编写|撰写|生成|给出|示范|"
            + "\\b(?:explain|describe|how|write|draft|give an example)\\b)", MATCH_FLAGS);
    private static final Pattern PROHIBITION = Pattern.compile(
            "^(?:(?:请|please)\\s*)?(?:不要|不得|禁止|无需|不需要|不用|不必|勿|避免|\\b(?:do not|don't|never)\\b)", MATCH_FLAGS);

    private final String summary;
    private final String refusal;

    AgentRequestRestriction(String summary, String refusal) {
        this.summary = summary;
        this.refusal = refusal;
    }

    public String summary() { return summary; }
    public String refusal() { return refusal; }

    public static Optional<AgentRequestRestriction> detect(String text) {
        if (text == null || text.isBlank()) return Optional.empty();
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFKC);
        for (String clause : normalized.split("[。；，、;\\r\\n]+")) {
            if (PROHIBITION.matcher(clause.stripLeading()).find()) continue;
            var reset = RESET_INSTRUCTIONS.matcher(clause);
            if (CREDENTIAL_REQUEST.matcher(reset.find() ? clause.substring(reset.end()) : clause).find()) {
                return Optional.of(PROTECTED_CREDENTIALS);
            }
        }
        for (String clause : normalized.split("[。；，、;\\r\\n]+|并且|然后|并(?=执行|运行|启动|打开|进入|调用)|(?i:\\band then\\b)")) {
            String command = clause.stripLeading();
            if (!PROHIBITION.matcher(command).find() && !TERMINAL_EXPLANATION.matcher(command).find()
                    && TERMINAL_REQUEST.matcher(command).find()) {
                return Optional.of(TERMINAL_EXECUTION);
            }
        }
        return Optional.empty();
    }
}
