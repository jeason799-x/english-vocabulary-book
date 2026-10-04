"""Original bilingual examples and a no-empty-example rule for new entries.

The bank works offline for the existing vocabulary. Unknown entries use the
normal dictionary lookup; an unavailable example must be supplied before saving.
"""
import re
from vocabulary_items import normalize_expression


EXAMPLES = {
    "crave": ("After a long day, I often crave something sweet.", "忙碌一天后，我常常想吃点甜食。"),
    "delicacies": ("The market sells local delicacies, including fresh seafood.", "这个市场出售包括新鲜海鲜在内的当地美食。"),
    "crumble": ("The old wall began to crumble after years of heavy rain.", "多年暴雨过后，那面旧墙开始坍塌。"),
    "frantically": ("She searched frantically for her passport before the flight.", "航班起飞前，她焦急地到处寻找护照。"),
    "substantial": ("The project requires a substantial investment of time.", "这个项目需要投入大量时间。"),
    "ruinous": ("The business struggled to survive the ruinous cost of repairs.", "这家企业难以承担高昂的维修费用，艰难维持经营。"),
    "refurnishing": ("They are refurnishing the apartment before moving in.", "他们正在重新布置公寓，然后再搬进去。"),
    "refurnish": ("We plan to refurnish the living room with simpler furniture.", "我们打算用更简洁的家具重新布置客厅。"),
    "cater": ("The restaurant can cater for groups of up to fifty people.", "这家餐厅能为最多五十人的团体提供餐饮服务。"),
    "inaction": ("Continued inaction will only make the problem worse.", "继续不采取行动只会让问题更严重。"),
    "mishandle": ("If you mishandle the equipment, you may damage it.", "如果操作不当，你可能会损坏设备。"),
    "mishandled": ("The complaint was mishandled, leaving the customer frustrated.", "这起投诉处理不当，让顾客感到很失望。"),
    "discredit": ("The scandal brought discredit on the organization.", "这起丑闻损害了该组织的声誉。"),
    "assess": ("The teacher will assess each student's progress at the end of the term.", "老师将在学期末评估每位学生的进步。"),
    "defer": ("They decided to defer the meeting until next week.", "他们决定将会议推迟到下周。"),
    "obesity": ("The report examines the factors associated with childhood obesity.", "这份报告探讨了与儿童肥胖有关的因素。"),
    "latter": ("Of the two proposals, the latter is more practical.", "这两个提议中，后者更切合实际。"),
    "interpret": ("Different readers may interpret the poem in different ways.", "不同的读者可能会以不同的方式理解这首诗。"),
    "concede": ("I must concede that your argument is convincing.", "我必须承认，你的论点很有说服力。"),
    "incidence": ("The study found a lower incidence of the disease in this region.", "研究发现，这个地区该疾病的发病率较低。"),
    "assortment": ("The shop offers an assortment of handmade gifts.", "这家店提供各种各样的手工礼品。"),
    "versatile": ("This versatile tool can be used for several different tasks.", "这个多功能工具可以用于好几种不同的任务。"),
    "compliment": ("She gave me a lovely compliment on my presentation.", "她对我的演讲给予了很好的称赞。"),
    "scramble": ("There was a scramble for the last few tickets.", "大家争抢最后几张票。"),
    "obsession": ("His obsession with perfection makes it hard for him to finish projects.", "他对完美的执着让他很难完成项目。"),
    "symptom": ("A persistent cough can be a symptom of several different conditions.", "持续咳嗽可能是多种不同疾病的症状。"),
    "rigorously": ("The team tested the new software rigorously before releasing it.", "团队在发布新软件前对它进行了严格测试。"),
    "evasive": ("He gave an evasive answer instead of explaining what happened.", "他给了一个含糊其辞的回答，没有解释发生了什么。"),
    "detrimentally": ("Constant noise can detrimentally affect students' concentration.", "持续的噪声会对学生的注意力产生不利影响。"),
    "aversion": ("She has a strong aversion to wasting food.", "她非常反感浪费食物。"),
    "diminish": ("As the sun went down, the heat began to diminish.", "随着太阳落下，暑热开始减弱。"),
    "akin": ("His reaction was akin to surprise rather than anger.", "他的反应更像是惊讶，而不是愤怒。"),
    "legitimize": ("The election was intended to legitimize the new government.", "这次选举旨在赋予新政府合法性。"),
    "paradigm": ("The discovery challenged the existing scientific paradigm.", "这一发现挑战了现有的科学范式。"),
    "candidates": ("The company interviewed five candidates for the position.", "公司面试了应聘该职位的五位候选人。"),
    "volume": ("Please turn down the volume while I am studying.", "我学习时，请把音量调低一些。"),
    "spectrum": ("The course covers a broad spectrum of topics.", "这门课程涵盖了广泛的主题。"),
    "molecule": ("A water molecule contains two hydrogen atoms and one oxygen atom.", "一个水分子包含两个氢原子和一个氧原子。"),
    "potent": ("Her speech was a potent reminder of the importance of education.", "她的演讲有力地提醒了人们教育的重要性。"),
    "dispense": ("The machine can dispense hot and cold water.", "这台机器可以供应热水和冷水。"),
    "strain": ("Working long hours put a strain on their relationship.", "长时间工作让他们的关系承受了压力。"),
    "antibiotic": ("The doctor prescribed an antibiotic for the bacterial infection.", "医生为这次细菌感染开了一种抗生素。"),
    "utilize": ("We should utilize the available resources more effectively.", "我们应该更有效地利用现有资源。"),
    "optimal": ("The team is looking for the optimal solution to the problem.", "团队正在寻找这个问题的最佳解决方案。"),
    "incorporate": ("We will incorporate your suggestions into the final report.", "我们会把你的建议纳入最终报告。"),
    "yield": ("Better irrigation helped increase the crop yield.", "更好的灌溉帮助提高了作物产量。"),
    "creep": ("We watched the fog creep slowly across the valley.", "我们看着雾气缓缓地蔓延过山谷。"),
    "astronomical": ("The cost of renting an apartment here is astronomical.", "在这里租公寓的费用高得惊人。"),
    "paycheck": ("She set aside part of her first paycheck for savings.", "她把第一份工资的一部分存了起来。"),
    "slave": ("The novel tells the story of a slave who fought for freedom.", "这部小说讲述了一名奴隶争取自由的故事。"),
    "anticipation": ("The children waited in anticipation of the school trip.", "孩子们满怀期待地等待学校组织的旅行。"),
    "means": ("Public transport is an affordable means of getting around the city.", "公共交通是在城里出行的一种经济实惠的方式。"),
    "indifference": ("Her suggestion was met with complete indifference.", "她的建议遭到了完全冷漠的对待。"),
    "thriftiness": ("His thriftiness helped him save enough money for college.", "他的节俭帮助他攒够了上大学的钱。"),
    "counterpart": ("The minister met with her French counterpart to discuss cooperation.", "这位部长与法国的对口部长会面，讨论合作事宜。"),
    "deadlock": ("The talks reached a deadlock over the issue of funding.", "谈判在资金问题上陷入了僵局。"),
    "account": ("She gave a detailed account of what had happened.", "她详细讲述了发生的事情。"),
    "executive": ("A senior executive explained the company's new strategy.", "一位高级管理人员解释了公司的新战略。"),
    "enact": ("The government plans to enact a law protecting personal data.", "政府计划制定一部保护个人数据的法律。"),
    "diffuse": ("The scent of fresh bread began to diffuse through the kitchen.", "新鲜面包的香气开始在厨房里弥漫。"),
    "articulate": ("She is an articulate speaker who explains complex ideas clearly.", "她是一位表达清晰的演讲者，能把复杂的想法讲明白。"),
    "bilateral": ("The two countries signed a bilateral trade agreement.", "两国签署了一项双边贸易协定。"),
    "consulate": ("He contacted the consulate after losing his passport abroad.", "他在国外丢失护照后联系了领事馆。"),
    "assure": ("I can assure you that your information will remain private.", "我可以向你保证，你的信息将得到保密。"),
    "continental": ("The train connects several cities in continental Europe.", "这趟列车连接了欧洲大陆的几个城市。"),
    "administration": ("The school administration announced a new attendance policy.", "学校管理部门宣布了一项新的考勤政策。"),
    "irretrievably": ("The original files were irretrievably lost when the drive failed.", "硬盘发生故障时，原始文件丢失且无法恢复。"),
    "content": ("The course content is updated at the start of every year.", "这门课程的内容在每年年初更新。"),
    "inventory": ("The manager checked the inventory before placing a new order.", "经理在下新订单前检查了库存。"),
    "file": ("Please save the file before closing the program.", "关闭程序前，请保存文件。"),
    "conveyor": ("The boxes moved along the conveyor toward the loading area.", "箱子沿着输送机向装货区移动。"),
    "sophisticate": ("As a seasoned sophisticate, she felt at ease in elegant company.", "作为一个久经世故的人，她在举止优雅的人群中感到很自在。"),
    "sophisticated": ("The laboratory uses sophisticated equipment to analyze samples.", "这间实验室使用精密设备分析样本。"),
    "allotting": ("The organizer is allotting ten minutes to each speaker.", "组织者正在为每位发言者分配十分钟。"),
    "allot": ("We should allot enough time to review each chapter.", "我们应该分配足够的时间来复习每一章。"),
    "executives": ("The executives met to discuss the company's future.", "高管们开会讨论了公司的未来。"),
    "obscure": ("The article refers to an obscure event in local history.", "这篇文章提到了地方史上一件鲜为人知的事件。"),
    "ascertain": ("We need to ascertain the cause of the error before making changes.", "我们需要在进行修改前查明错误的原因。"),
    "preoccupied": ("She was so preoccupied with work that she missed the announcement.", "她一心忙于工作，没有听到那则通知。"),
    "hamper": ("They packed sandwiches and fruit into a picnic hamper.", "他们把三明治和水果装进了野餐篮。"),
    "obstructive": ("His obstructive behavior delayed the whole project.", "他的阻挠行为拖延了整个项目。"),
    "rectification": ("The report called for the immediate rectification of the accounting errors.", "报告要求立即纠正账目中的错误。"),
    "upstairs": ("The upstairs bedroom gets plenty of sunlight.", "楼上的卧室有充足的阳光。"),
    "watertight": ("Make sure the container is watertight before putting it in your bag.", "把容器放进包里之前，要确保它不会漏水。"),
    "proofread": ("Please proofread the essay before handing it in.", "提交作文之前，请先校对一遍。"),
    "align": ("Align the edges of the paper before cutting it.", "裁剪纸张前，先把纸的边缘对齐。"),
    "delusional": ("The character becomes delusional and loses touch with reality.", "这个角色变得妄想，逐渐脱离了现实。"),
    "amendment": ("The committee proposed an amendment to the contract.", "委员会提议修改合同。"),
    "amendments": ("Several amendments were made before the document was approved.", "文件获批前作了几项修改。"),
    "interim": ("An interim manager will lead the team until a replacement is hired.", "在聘到正式接任者之前，一位临时经理将带领团队。"),
    "legitimacy": ("Observers questioned the legitimacy of the election.", "观察人士质疑这次选举的合法性。"),
    "diplomat": ("The diplomat helped the two sides reach an agreement.", "这位外交官帮助双方达成了协议。"),
    "rhetoric": ("The speech contained plenty of rhetoric but few concrete proposals.", "这篇演讲充满了华丽辞藻，却鲜有具体建议。"),
    "discourse": ("The book explores how technology has changed public discourse.", "这本书探讨了技术如何改变公共讨论。"),
    "prerequisite": ("Students must complete the prerequisite courses before applying.", "学生必须修完先修课程才能申请。"),
    "unanimous": ("The committee reached a unanimous decision.", "委员会作出了一致的决定。"),
    "board": ("He nailed a wooden board across the broken window.", "他在破损的窗户上钉了一块木板。"),
    "implement": ("A hoe is a useful implement for working the soil.", "锄头是一种实用的耕土工具。"),
    "hierarchy": ("The company has a clear hierarchy of management roles.", "这家公司有明确的管理职位层级。"),
    "managerial": ("The position requires strong managerial skills.", "这个职位要求具备很强的管理能力。"),
    "cynical": ("He became cynical about promises that were never kept.", "对于那些从未兑现的承诺，他变得冷嘲热讽。"),
    "rise to the challenge": ("With support from her team, she was able to rise to the challenge.", "在团队的支持下，她成功迎接并应对了挑战。"),
    "apple": ("She packed an apple in her lunch bag.", "她在午餐袋里放了一个苹果。"),
    "orange": ("He peeled an orange after lunch.", "午饭后，他剥了一个橙子。"),
    "pear": ("This ripe pear tastes sweet and juicy.", "这个熟透的梨尝起来又甜又多汁。"),
    "first and foremost": ("First and foremost, we need to keep everyone safe.", "首先，我们需要确保每个人的安全。"),
    "pay attention to": ("Please pay attention to the instructions before you begin.", "开始之前，请留意这些说明。"),
    "take care of": ("She will take care of her younger brother this afternoon.", "今天下午她会照顾弟弟。"),
    "be interested in": ("They seem to be interested in the history of the city.", "他们似乎对这座城市的历史感兴趣。"),
    "fall short": ("Without enough practice, even talented students can fall short of their goals.", "缺乏足够的练习，即使有天赋的学生也可能达不到目标。"),
    "goal-oriented": ("A goal-oriented team focuses on results and clear priorities.", "一个以目标为导向的团队注重成果和明确的优先事项。"),
    "tenants": ("The tenants asked the landlord to repair the heating system.", "租客们要求房东维修供暖系统。"),
    "mandatory": ("Attendance at the safety training session is mandatory.", "参加这次安全培训是强制要求。"),
    "solicitor": ("She consulted a solicitor before signing the contract.", "她在签订合同前咨询了一位律师。"),
}


def has_example(payload):
    return bool(re.search(r"[A-Za-z]", str(payload.get("example") or "").strip()))


def complete_example(payload, *, required=False):
    result = dict(payload)
    if not has_example(result):
        pair = EXAMPLES.get(normalize_expression(str(result.get("word") or "")))
        if pair:
            result["example"], result["translation"] = pair
    if required and not has_example(result):
        raise ValueError(f"{result.get('word', '这条内容')} 缺少英文例句。请自动查询或补充例句后再保存。")
    return result


def enrich_entry(payload, lookup):
    """Merge only missing fields; lookup is supplied by the UI's background job."""
    result = complete_example(payload)
    if not has_example(result):
        result["example"] = ""
    if not result.get("meaning", "").strip() or not has_example(result):
        found = lookup(result["word"])
        for key in ("meaning", "phonetic", "part_of_speech", "usage", "example", "translation"):
            if not result.get(key) and found.get(key):
                result[key] = found[key]
    if not result.get("meaning", "").strip():
        raise ValueError("缺少中文释义，请补全后再保存。")
    return complete_example(result, required=True)


def repair_example_data(data, updates=None):
    """Repair this store's own entries and checkpoint copies, never another store.

    Only example/translation fields change. Unknown words stay available for
    background dictionary lookup; failure never removes a word or its progress.
    """
    updates = {normalize_expression(key): value for key, value in (updates or {}).items()}
    changed = 0

    def repair_record(record):
        nonlocal changed
        if has_example(record):
            return
        key = normalize_expression(str(record.get('word') or ''))
        filled = updates.get(key) or complete_example(record)
        if has_example(filled):
            record['example'] = filled['example']
            record['translation'] = filled.get('translation', '')
            changed += 1

    for record in data.get('words', []):
        repair_record(record)

    def repair_checkpoint(value):
        if isinstance(value, dict):
            if 'word' in value and 'id' in value:
                repair_record(value)
            for child in value.values():
                repair_checkpoint(child)
        elif isinstance(value, list):
            for child in value:
                repair_checkpoint(child)
    repair_checkpoint(data.get('active_session'))
    return changed
