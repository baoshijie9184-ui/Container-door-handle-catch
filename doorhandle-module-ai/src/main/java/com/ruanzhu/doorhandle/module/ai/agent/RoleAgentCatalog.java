package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.util.List;

/** 两类主 Agent，专业能力按可用门面注册，只声明已实现工具。 */
public final class RoleAgentCatalog {
    private RoleAgentCatalog() {}
    public record Definition(String id, String description, List<String> tools) {}
    public static String mainId(AgentActor actor) {
        return actor.supervisor() ? "supervisor-main" : "employee-main";
    }
    public static List<Definition> specialists(AgentActor actor) {
        return specialists(actor,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation) {
        return specialists(actor,confirmation,false,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation,boolean reports,boolean drafts) {
        return specialists(actor,confirmation,reports,drafts,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation,boolean reports,boolean drafts,boolean retry) {
        return specialists(actor,confirmation,reports,drafts,retry,false);
    }
    public static List<Definition> specialists(AgentActor actor,boolean confirmation,boolean reports,boolean drafts,boolean retry,boolean creation) {
        var result=new java.util.ArrayList<Definition>(actor.supervisor() ? List.of(
                new Definition("detection-quality", confirmation?"检测质检查询，提出需人工确认的质检分配":"检测质检管理，查询任务和质检记录", confirmation?List.of("search_detection_tasks", "get_task_detail", "get_quality_records","propose_quality_assignment"):List.of("search_detection_tasks", "get_task_detail", "get_quality_records")),
                new Definition("resource-management", "设备状态、采集告警及单体应用固定探针健康查询，不执行告警处置或运维修复", List.of("list_devices", "list_device_alerts", "get_device_alert", "get_system_health")),
                new Definition("model-ops", "检测模型目录、登记评估指标和发布配置查询，不推断实际灰度流量或执行发布", List.of("list_models", "get_model_operations")),
                new Definition("department-analytics", "按最近天数汇总当前单企业检测工作量；不支持单个任务明细、任务状态或单任务缺陷统计，这些应交给 detection-quality", List.of("get_department_work_metrics")))
                : List.of(
                new Definition("detection-task", "本人及分派的检测任务查询；单任务进度、缺陷总数和当前复核状态/结论可一次获取", List.of("get_my_detection_tasks", "get_task_detail")),
                new Definition("quality-review", "本人任务质检历史列表查询；单任务当前复核状态/结论用 get_task_detail，不等于历史列表", List.of("get_my_quality_records", "get_task_detail")),
                new Definition("device-status", "查询本人任务关联的设备名称；暂不提供实时设备状态和绑定设备清单", List.of("get_task_detail")),
                new Definition("personal-analytics", "按最近天数汇总本人及分派任务工作量；不支持单任务明细或状态，应交给 detection-task", List.of("get_my_work_metrics"))));
        if(retry) {
            String target=actor.supervisor()?"detection-quality":"detection-task";
            for(int i=0;i<result.size();i++)if(result.get(i).id().equals(target)) {
                var current=result.get(i);var tools=new java.util.ArrayList<>(current.tools());tools.add("propose_detection_retry");
                result.set(i,new Definition(current.id(),current.description()+"；按用户明确要求提出检测重试，仍需卡片人工确认",List.copyOf(tools)));
            }
        }
        if(creation){
            String target=actor.supervisor()?"detection-quality":"detection-task";
            for(int i=0;i<result.size();i++)if(result.get(i).id().equals(target)){
                var current=result.get(i);var tools=new java.util.ArrayList<>(current.tools());tools.add("propose_detection_creation");
                result.set(i,new Definition(current.id(),current.description()+"；从当前会话图片提出新检测，先补齐采集信息，再人工确认",List.copyOf(tools)));
            }
        }
        if(reports)result.add(new Definition("report-assistant",actor.supervisor()?"查询授权报告与待审批列表，按明确请求保存本人草稿；审批请到报告页面人工确认":"查询本人报告，按明确请求编写或编辑本人草稿；提交审批请到报告页面",
                drafts?List.of("list_quality_reports","get_quality_report","create_report_draft","edit_report_draft"):List.of("list_quality_reports","get_quality_report")));
        return List.copyOf(result);
    }
    /** Capabilities come from the current role catalog rather than an independent routing registry. */
    public static String routingGuide(List<Definition> definitions) {
        String catalog=definitions.stream().map(d->d.id()+"："+d.description()+"；可用业务工具 "+String.join("、",d.tools()))
                .collect(java.util.stream.Collectors.joining("\n"));
        return "\n专业路由目录（仅当前账号可用）：\n"+catalog
                +"\n按所需事实和工具选择专业 Agent，不要仅凭‘统计’一词路由。提供 taskId 的单任务状态、缺陷总数、复核结论应使用具备 get_task_detail 的检测专业 Agent；时间范围的总体工作量才使用 work_metrics。"
                +"委派时保留用户提供的编号、筛选、范围和只读限制。需要多个专业能力时分开委派，再核对范围汇总。"
                +"子 Agent 缺少工具仅代表该专业的能力边界，不代表系统没有此能力：重新核对目录，并在已批准范围内交给有相应工具的专业 Agent；不得用企业总量代替单任务数据。"
                +"当前员工角色未开放的企业设备、告警或模型管理能力，应说明本账号权限或接入范围受限，不得泛化为整个系统不支持，也不擅自切换主管身份。"
                +taskDetailGuide()
                +"get_task_detail 只有任务缺陷总数，不含六分类分布。工具没有的字段应明确说明未知，不从总数推算类别。";
    }
    public static String taskDetailGuide() {
        return "单任务的处理状态、缺陷总数、当前复核状态及复核结论已包含在一次 get_task_detail 结果中。"
                +"处理状态和复核状态是不同字段。reviewStatus 为 PENDING 表示待复核或尚未复核，不表示正在复核；处理完成也不等于已经复核、审批通过或业务放行。"
                +"同一任务同时询问这些字段时，只委派一个具备该工具的专业 Agent 并查询一次，不拆成检测和质检两次委派。"
                +"仅在用户明确需要历史质检记录列表时才调用 get_my_quality_records/get_quality_records；这些是分页列表工具，没有 taskId 筛选参数，不能为单任务当前复核情况额外读取整个列表。";
    }
    public static String executionGuide(AgentActor actor) {
        return "\n执行与回答边界：需要当前业务事实且参数齐全时，本轮实际调用已注册的专业委派工具，再按回执汇总。"
                + "不得只回答‘我将委派查询’就结束，也不得把打算调用、生成工具名称或历史回执说成已启动本轮查询。"
                + "确认权限或接入能力不足时，应直接说明当前账号的具体范围；缺少权限不是缺少参数，不为此使用 ask_user_question 反复询问用户是否继续。"
                + "查询返回无访问权限或资源不存在时，保留这一拒绝，不推断资源是否存在，不建议切换他人身份、不索取他人凭据，也不自动改查企业总量。"
                + "只有用户请求范围已获授权且补充必要业务参数确实可以继续时才追问；询问权限或功能范围本身可以直接解释。"
                + (actor.supervisor()
                    ? "当前主管可用范围仍以本次目录和实际工具为准，未提供的实时能力应明确说明。"
                    : "当前是员工账号：只可读取本人及分派任务；任务详情中的设备名称不是实时在线状态。全企业设备实时在线状态不在本账号可读范围，直接说明员工权限限制，不要求任务编号或让用户选择继续查询。");
    }
    public static String delegationDescription(Definition definition) {
        return definition.description()+"。可用业务工具："+String.join("、",definition.tools())+"。请在 question 中保留任务编号、时间范围和用户限制。";
    }
}
