from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.modules.recruitment.schemas import JobImportItem


@dataclass(frozen=True)
class PublicCampaign:
    company: str
    source_url: str
    source_title: str
    published_at: datetime | None
    positions: tuple[str, ...]
    city: str = ""
    education: str = ""
    experience: str = ""
    salary_text: str = ""
    requirements: str = ""
    benefits: tuple[str, ...] = ()
    work_schedule: str = ""
    descriptions: dict[str, str] = field(default_factory=dict)
    source_type: str = "企业招聘公告"


# These records are transcribed only from the cited public pages. Campaign-wide fields are
# repeated across their listed positions; fields not stated by the source are deliberately empty.
PUBLIC_CAMPAIGNS: tuple[PublicCampaign, ...] = (
    PublicCampaign(
        company="朗新科技集团股份有限公司",
        source_url="https://career.hebut.edu.cn/correcruit/content/id/68924.html",
        source_title="朗新科技有限股份公司2026校园招聘岗位总览",
        published_at=None,
        positions=(
            "储备项目经理",
            "算法工程师",
            "Java开发工程师",
            "产品经理",
            "咨询助理",
            "解决方案工程师",
            "UI设计师",
            "测试工程师",
            "Python开发工程师",
            "应付会计",
        ),
        education="本科及以上",
        experience="2026届应届毕业生",
        salary_text="本科13-20万元/年；硕士20-40万元/年",
        requirements="2026届全日制本科及以上学历应届毕业生；专业要求以招聘公告具体岗位说明为准。",
        benefits=(
            "六险一金",
            "人才补贴",
            "弹性工作制",
            "年终奖0-4个月",
            "优秀员工股票激励",
            "提供住宿",
            "节日礼",
            "生日礼",
            "结婚生育补贴",
            "团建活动",
        ),
        work_schedule="弹性工作制",
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="华为云计算技术有限公司",
        source_url="https://www.huaweicloud.com/lab/paas/sacampusrecruitment.html",
        source_title="华为云数字化平台技术创新Lab 2026校园招聘",
        published_at=None,
        positions=(
            "AI软件工程师",
            "AI应用工程师",
            "AI安全工程师",
            "AI Infra工程师",
            "软件开发工程师",
            "云计算开发工程师",
        ),
        city="北京/上海/东莞",
        experience="校园招聘",
        requirements="岗位要求以华为云公开招聘页面中各岗位的独立说明为准。",
        descriptions={
            "AI软件工程师": (
                "计算机或人工智能相关专业；具备大型软件项目经验；"
                "熟悉至少一门编程语言及主流深度学习框架。"
            ),
            "AI应用工程师": (
                "人工智能、计算机、软件工程、电子信息或自动化相关专业；"
                "熟悉大模型应用开发框架、模型原理及至少一门编程语言。"
            ),
            "AI安全工程师": (
                "人工智能、机器学习、数学、网络安全、计算机、软件、"
                "信息安全或密码学相关专业；掌握至少一门开发语言。"
            ),
            "AI Infra工程师": (
                "计算机科学、计算机工程、人工智能、电子信息技术、"
                "软件工程或机器学习相关专业；具备代码和算法实现能力。"
            ),
            "软件开发工程师": (
                "计算机、软件、通信等相关专业；掌握至少一种编程语言，了解数据结构和算法。"
            ),
            "云计算开发工程师": (
                "计算机、软件相关专业；熟悉至少一种编程语言，具备虚拟化、"
                "计算、网络、存储、安全、数据库或分布式架构知识者优先。"
            ),
        },
        source_type="企业官网",
    ),
    PublicCampaign(
        company="金蝶软件（中国）有限公司",
        source_url="https://career.hebut.edu.cn/home/correcruit/content/id/80371.html",
        source_title="金蝶2027届校园招聘简章",
        published_at=datetime(2026, 9, 10, tzinfo=UTC),
        positions=(
            "产品经理",
            "实施顾问",
            "Agent开发工程师",
            "Harness算法工程师",
            "大模型算法工程师",
            "AI开发工程师",
            "AI产品经理",
            "AI产品体验设计",
            "客户经营",
            "市场推广",
        ),
        city="深圳/上海/南京/北京/长沙/厦门等",
        education="本科",
        experience="2027届应届毕业生（毕业时间2026-10-01至2027-09-30）",
        salary_text="10000元以上",
        requirements="计算机科学、人工智能、数学、统计学等相关专业；具体岗位要求以网申信息为准。",
        benefits=(
            "员工餐厅",
            "免费夜宵（深圳园区）",
            "年度体检",
            "商业保险",
            "节日福利",
            "带薪休假",
            "公租房申请资源",
            "导师带教",
        ),
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="北京微步在线科技有限公司",
        source_url="https://jobs.tiangong.edu.cn/correcruit/content/id/54276.html",
        source_title="北京微步在线科技有限公司2026年校园招聘",
        published_at=datetime(2026, 3, 18, tzinfo=UTC),
        positions=(
            "Java开发工程师",
            "Windows开发工程师",
            "前端开发工程师",
            "Python开发工程师",
            "机器学习工程师",
            "安全分析师",
            "木马分析师",
            "安全服务工程师",
            "安全研究员",
            "产品经理",
            "产品运营",
            "销售经理",
            "客户成功经理",
            "售前工程师",
        ),
        city="北京",
        education="本科在学",
        experience="2026届应届毕业生（最高学历毕业后无全职工作经验）",
        salary_text="10000元以上",
        requirements="技术岗位面向计算机、软件工程、数据挖掘、大数据处理、信息与通信工程、控制科学与工程等相关专业；具体要求以岗位类别为准。",
        benefits=(
            "八险一金",
            "期权激励",
            "特别假期",
            "工作餐",
            "免费零食饮料",
            "带薪年假",
            "年终奖金",
            "节日礼品",
            "周年礼物",
            "工作居住证",
            "婚育假",
            "年度体检",
            "定期培训",
        ),
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="腾讯云计算（西安）有限责任公司",
        source_url="https://jobs.tiangong.edu.cn/correcruit/content/id/54244.html",
        source_title="腾讯云智研发2026届校园招聘",
        published_at=datetime(2026, 3, 17, tzinfo=UTC),
        positions=(
            "后台开发",
            "客户端开发",
            "前端开发",
            "测试开发",
            "运营开发",
            "数据分析",
            "数据工程",
            "算法工程师",
            "应用运维安全",
            "后台策略安全",
            "技术运营",
            "系统测试",
            "技术产品",
            "产品策划/运营",
            "技术咨询",
            "视觉设计",
            "交互设计",
            "交付项目管理",
        ),
        city="西安/武汉/长沙/重庆/厦门",
        education="本科及以上",
        experience="毕业时间2025-01-01至2026-12-31",
        salary_text="10000元以上",
        requirements="本科或以上学历，相关专业；具备扎实的编程或设计能力，掌握相关编程语言或设计软件，具有学习、协作、逻辑分析和沟通表达能力。",
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="多益网络有限公司",
        source_url="https://career.hebut.edu.cn/correcruit/content/id/78997.html",
        source_title="软件工程师【27届校招】",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        positions=("软件工程师【27届校招】",),
        city="浙江/湖北/广东",
        education="本科",
        experience="27届校招",
        salary_text="目标年薪17-27万元；页面另列转正后6000-8000元/月",
        requirements="计算机或理工科相关专业；掌握至少一种编程语言以及基本数据结构和算法知识。",
        benefits=("奖金", "法定每月不超过36小时的加班费"),
        work_schedule="可能包含法定每月不超过36小时加班，具体以实际工作时间为准",
        descriptions={
            "软件工程师【27届校招】": (
                "参与软件产品功能开发与维护、项目优化和代码调优，"
                "并按业务需要完成调研、数据分析或方案设计。"
            )
        },
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="中国移动通信集团四川有限公司",
        source_url="https://career.hebut.edu.cn/correcruit/content/id/77637.html",
        source_title="中国移动四川公司2026春季校园招聘公告",
        published_at=datetime(2026, 3, 18, tzinfo=UTC),
        positions=(
            "网络运维工程师-传输网",
            "解决方案工程师",
            "项目交付工程师-政企",
            "网络运维工程师-无线网",
            "网络运营工程师-政企",
            "动力运维工程师",
            "解决方案支撑工程师",
            "系统支持工程师",
            "网络优化工程师-无线网",
            "业务支撑工程师-5G及物联网",
            "网络运营工程师-云资源池",
            "算法开发工程师",
            "大数据开发工程师",
            "网络信息安全工程师",
            "AI算法工程师",
            "大模型及人工智能工程师",
            "网络安全管理工程师",
            "网络支撑工程师-智慧家庭",
            "业务支撑工程师-专线及云网",
        ),
        city="四川",
        education="本科及以上",
        experience="2025年1月至2026年7月毕业",
        salary_text="8000-10000元/月",
        requirements="技术类面向计算机科学与技术、软件工程、网络工程、物联网工程、人工智能、数学、统计学、通信工程、信息工程、电子信息工程等相关专业；具体岗位以公告为准。",
        source_type="高校就业官网转载企业招聘公告",
    ),
    PublicCampaign(
        company="云尖信息技术有限公司",
        source_url="https://scdc.jnu.edu.cn/attachment/jnu/ueditor/file/20260305/4872_%E4%BA%91%E5%B0%96%E4%BF%A1%E6%81%AF2026%E5%B1%8A%E6%A0%A1%E5%9B%AD%E6%8B%9B%E8%81%98%E7%AE%80%E7%AB%A0.pdf",
        source_title="云尖信息2026届校园招聘简章",
        published_at=None,
        positions=("2026届技术类校园招聘岗位",),
        city="杭州萧山区",
        education="本科/硕士",
        experience="2026届应届毕业生",
        salary_text="综合年薪17.5-27万元，AI岗位另议",
        requirements="2026届应届本科或硕士，计算机类、电子信息类相关专业；具备创新解题、学习适应、协作沟通能力。",
        benefits=(
            "五险一金",
            "带薪年假",
            "法定节假日",
            "节日福利",
            "定期团建",
            "下午茶",
            "免费健身中心",
            "打车补贴",
            "年度体检",
            "培训期住宿",
            "人才公寓机会",
            "年终浮动奖金",
            "股权激励",
        ),
        work_schedule="周一至周五8:30-18:00，午休1.5小时，周末双休",
        source_type="高校就业官网公开招聘PDF",
    ),
)


def iter_public_jobs() -> list[JobImportItem]:
    jobs: list[JobImportItem] = []
    for campaign in PUBLIC_CAMPAIGNS:
        for position in campaign.positions:
            digest = hashlib.sha256(f"{campaign.source_url}|{position}".encode()).hexdigest()[:32]
            description = campaign.descriptions.get(position, "")
            jobs.append(
                JobImportItem(
                    source="public-web",
                    external_id=digest,
                    source_url=campaign.source_url,
                    title=position,
                    company=campaign.company,
                    city=campaign.city,
                    education=campaign.education,
                    experience=campaign.experience,
                    salary_text=campaign.salary_text,
                    requirements=campaign.requirements,
                    benefits=list(campaign.benefits),
                    work_schedule=campaign.work_schedule,
                    description=description,
                    published_at=campaign.published_at,
                    raw_json={
                        "source_title": campaign.source_title,
                        "source_type": campaign.source_type,
                        "extraction_note": "仅录入公开页面明确陈述的信息；未公开字段保持为空。",
                    },
                )
            )
    return jobs
