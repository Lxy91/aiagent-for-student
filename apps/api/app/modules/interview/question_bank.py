TECHNICAL_QUESTIONS = {
    "general": [
        "请解释浏览器从解析 HTML 到完成页面渲染的过程。",
        "重排和重绘是什么关系，项目中如何减少它们？",
        "请讲讲 JavaScript 事件循环，以及微任务和宏任务的执行顺序。",
        "防抖和节流分别适用于哪些场景，如何实现一个防抖函数？",
        "如何实现支持循环引用、Map、Set、Date 和 RegExp 的深拷贝？",
        "浏览器强缓存和协商缓存有什么区别？",
        "WebSocket 心跳和断线重连如何设计，为什么使用指数退避？",
        "大文件上传或 Excel 导入如何分片、展示进度并避免阻塞主线程？",
    ],
    "react": [
        "React 组件生命周期如何映射到函数组件和 Hooks？",
        "useMemo 和 useCallback 有什么区别，什么时候不应该使用？",
        "React Fiber 为什么可以中断渲染，Scheduler 和 Lane 分别做什么？",
        "Redux 的数据流是什么，和 Vuex 的 Action、Mutation 有什么区别？",
        "项目中的动态表单如何减少无意义渲染和频繁请求？",
        "不定高虚拟列表如何定位起始项并进行滚动高度补偿？",
        "single-spa 子应用之间如何通信、隔离样式和共享依赖？",
    ],
    "vue": [
        "v-if 和 v-show 有什么区别，应该如何选择？",
        "Vue 中常用的组件通信方式有哪些？",
        "Vuex 的 Action、Mutation、State 数据流是什么？",
        "Vue 项目从 npm run build 到产物生成经历了哪些步骤？",
        "微前端场景中如何解决子应用通信、样式冲突和公共依赖共享？",
        "不定高虚拟列表为什么会抖动，如何通过位置缓存和高度补偿解决？",
    ],
}

HR_QUESTIONS = [
    "请介绍你最有代表性的实习或项目经历，以及你承担的职责。",
    "项目中遇到过最棘手的问题是什么，你如何分析并推动解决？",
    "为什么考虑离开上一家公司，为什么选择我们？",
    "你的职业规划是什么，前端和 AI 方向如何结合？",
    "你通常如何学习新技术并验证学习效果？",
    "同时面对多个项目或很多琐碎任务时，你如何确定优先级？",
    "你希望加入什么样的团队，你能为团队带来什么？",
    "如果需要切换到不熟悉的技术栈，你预计多久能上手，计划是什么？",
]


def build_interview_prompt(track: str, interview_type: str, difficulty: str) -> str:
    track_name = {"react": "React", "vue": "Vue", "general": "泛前端"}.get(track, "泛前端")
    level = {"standard": "标准", "advanced": "进阶", "pressure": "压力面"}.get(difficulty, "标准")
    technical = TECHNICAL_QUESTIONS.get(track, TECHNICAL_QUESTIONS["general"])
    if track != "general":
        technical = TECHNICAL_QUESTIONS["general"][:4] + technical
    questions = HR_QUESTIONS if interview_type == "hr" else technical
    if interview_type == "mixed":
        questions = technical + HR_QUESTIONS[:5]
    bank = "\n".join(f"- {question}" for question in questions)
    return (
        f"你是一名专业、自然、友好但有判断力的{track_name}面试官，正在进行{level}难度面试。"
        "先简短问候并请候选人自我介绍。之后每轮只问一个问题，必须等待回答。"
        "优先针对候选人刚才的回答追问证据、实现细节、权衡、边界情况和改进方案；"
        "追问完成后再从下方真实面经题库选择新题，避免机械地按顺序念题。"
        "回答含糊时要求给具体项目案例；回答有错误时先继续追问，不要立即给标准答案。"
        "候选人说继续、下一题或不会时，简短回应后换题。表达口语化简洁，不读 Markdown。"
        f"\n真实前端面经题库：\n{bank}"
    )
