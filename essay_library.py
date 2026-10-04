"""Essay records and their reusable vocabulary, independent of the interface."""
from copy import deepcopy
from datetime import datetime
import re
import uuid
from vocabulary_items import expression_pattern
from example_bank import complete_example


def word_count(original):
    return len(re.findall(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*", original))


def normalize_essay(payload, previous=None):
    code = str(payload.get('code', '')).strip()
    original = str(payload.get('original', '')).strip()
    if not code or not original:
        raise ValueError('请填写作文编号和英文原文。')
    record = {key: str(payload.get(key, '')).strip()
              for key in ('code', 'title', 'topic', 'original', 'translation', 'thinking', 'source_text')}
    for key in ('collocations', 'templates'):
        record[key] = []
        for row in payload.get(key, []):
            expression = str(row.get('expression', '')).strip()
            meaning = str(row.get('meaning', '')).strip()
            if not expression or not meaning:
                raise ValueError('每条搭配或句型都需要英文和中文释义。')
            record[key].append({field: str(row.get(field, '')).strip()
                                for field in ('expression', 'meaning', 'note')})
    timestamp = datetime.now().isoformat(timespec='seconds')
    record.update(id=previous['id'] if previous else str(uuid.uuid4()),
                  created_at=previous['created_at'] if previous else timestamp,
                  updated_at=timestamp)
    return record


def parse_expression_lines(text):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = re.split(r'\t|\s*[|｜]\s*', line.strip(), maxsplit=2)
        if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError(f'第 {number} 行需要“英文 | 中文释义 | 用法说明”，用法说明可以留空。')
        rows.append({'expression': parts[0].strip(), 'meaning': parts[1].strip(),
                     'note': parts[2].strip() if len(parts) > 2 else ''})
    return rows


def format_expression_lines(rows):
    return '\n'.join(' | '.join(row.get(key, '') for key in ('expression', 'meaning', 'note')).rstrip(' |')
                     for row in rows)


def vocabulary_payloads(essay):
    sentences = re.split(r'(?<=[.!?])\s+', essay.get('original', '').replace('**', '').strip('"'))
    result = []
    for row in essay.get('collocations', []):
        example = next((sentence for sentence in sentences if expression_pattern(row['expression']).search(sentence)), '')
        payload = {'word': row['expression'], 'meaning': row['meaning'], 'entry_type': 'phrase', 'example': example,
                   'usage': f"作文 {essay['code']}" + ('：' + row['note'] if row.get('note') else '')}
        result.append(complete_example(payload))
    return result


def _reusable_rows(block):
    if not block.strip():
        return []
    chunks = re.split(r'^\s*\d+[.、)]\s*', block, flags=re.M)
    if len(chunks) > 1:
        chunks = [chunk for chunk in chunks if chunk.strip()]
    else:
        chunks = [line for line in block.splitlines() if line.strip()]
    rows = []
    for index, chunk in enumerate(chunks, 1):
        chunk = chunk.strip()
        if '|' in chunk or '｜' in chunk or '\t' in chunk:
            rows.extend(parse_expression_lines(chunk))
            continue
        match = re.match(r'^\*\*(.+?)\*\*(.*)$', chunk, re.S)
        if match:
            expression, description = match.groups()
        else:
            parts = re.split(r'\n|\s*[—–]{1,2}\s*|\s+(?=[\u4e00-\u9fff])', chunk, maxsplit=1)
            if len(parts) != 2:
                raise ValueError(f'第 {index} 条表达缺少中文说明。可用“英文 | 中文释义 | 用法说明”。')
            expression, description = parts
        description = re.sub(r'^\s*[—–\-]+\s*', '', description.strip()).replace('**', '').strip()
        if not expression.strip() or not description:
            raise ValueError(f'第 {index} 条表达需要英文和中文说明。')
        rows.append({'expression': expression.strip(), 'meaning': description, 'note': ''})
    return rows


def parse_essay_text(text, phrase_candidates=None):
    """Read the user's complete Markdown-style essay without requiring separate forms."""
    source = text.strip().lstrip('\ufeff')
    lines = source.splitlines()
    if not lines:
        raise ValueError('请先粘贴完整的作文资料。')
    first = re.sub(r'^\s*#{1,6}\s*', '', lines[0]).replace('**', '').strip()
    first = re.sub(r'^(?:作文编号|编号)\s*[:：]\s*', '', first)
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', first):
        raise ValueError('第一行请填写作文编号，例如 CET6_202512_W_02，编号可以带 ** 或 # 标记。')
    aliases = {
        '英文原文': 'original', '作文原文': 'original', '原文': 'original',
        '中文翻译': 'translation', '翻译': 'translation',
        '写作思路': 'thinking', '思路': 'thinking',
        '固定搭配': 'collocations', '搭配': 'collocations', '短语': 'collocations',
        '模板句型': 'templates', '模板句子': 'templates',
        '值得背诵的模板句子/短语及说明': 'mixed',
        '值得背诵的模板句子／短语及说明': 'mixed',
        '值得背诵的句子/短语及说明': 'mixed',
    }
    sections = {key: [] for key in ('original', 'translation', 'thinking', 'collocations', 'templates', 'mixed')}
    current = 'original'
    metadata = {'code': first, 'title': '', 'topic': ''}
    for line in lines[1:]:
        heading = re.sub(r'^\s*#{1,6}\s*', '', line).replace('**', '').strip().rstrip(':：').strip()
        if heading in aliases:
            current = aliases[heading]
            continue
        meta = re.match(r'^(标题|主题|类型)\s*[:：]\s*(.+)$', heading)
        if meta and current == 'original' and not ''.join(sections['original']).strip():
            metadata['title' if meta[1] == '标题' else 'topic'] = meta[2]
            continue
        sections[current].append(line)
    result = {**metadata, 'source_text': source}
    for field in ('original', 'translation', 'thinking'):
        result[field] = '\n'.join(sections[field]).strip()
    if not result['original'] or not re.search(r'[A-Za-z]', result['original']):
        raise ValueError('没有识别到英文原文。请把原文放在编号下面，或放在“英文原文”标题下面。')
    result['collocations'] = _reusable_rows('\n'.join(sections['collocations']))
    result['templates'] = _reusable_rows('\n'.join(sections['templates']))
    for row in _reusable_rows('\n'.join(sections['mixed'])):
        target = 'templates' if word_count(row['expression']) > 8 or re.search(r'[.!?…]|\.{2,}', row['expression']) else 'collocations'
        result[target].append(row)
    # Reuse known expressions found in the original; explicit user definitions take priority.
    candidates = SAMPLE_ESSAY['collocations'] + (phrase_candidates or [])
    existing = {row['expression'].casefold() for row in result['collocations']}
    plain = result['original'].replace('**', '')
    for row in candidates:
        expression = row.get('expression', row.get('word', '')).strip()
        if not expression or expression.casefold() in existing:
            continue
        pattern = re.escape(expression).replace(r'\ ', r'\s+')
        if expression == 'rise to the challenge':
            pattern = r'rise\s+to\s+(?:the|these|a)\s+challenges?'
        if re.search(r'(?<!\w)' + pattern + r'(?!\w)', plain, re.I):
            result['collocations'].append({'expression': expression, 'meaning': row['meaning'],
                                           'note': row.get('note', row.get('usage', ''))})
            existing.add(expression.casefold())
    return result


SAMPLE_ESSAY = {
    'code': 'CET6_202512_W_01',
    'title': '大学生如何应对挑战',
    'topic': '六级 · 问题—对策',
    'original': '''"Living in an increasingly competitive world, college students should better prepare themselves to confront various challenges." **To rise to these challenges, they need to take concrete steps in several key areas.** **First and foremost, academic excellence remains the foundation.** Students should master professional knowledge and keep pace with new technologies. For example, a computer science major who learns artificial intelligence early may gain an edge in job hunting. **In addition, soft skills matter just as much as hard skills.** Communication, teamwork, and time management help graduates adapt to complex workplaces. They should also seek internships and volunteer work to gain practical experience. Such experiences can broaden their horizons and strengthen their competitiveness. **Last but not least, mental resilience should not be ignored.** Facing failure and pressure, students can stay positive through exercise, hobbies, and support from friends. **Therefore, only by improving knowledge, skills, and character can college students turn challenges into opportunities and build a promising future.**''',
    'translation': '''“生活在一个竞争日益激烈的世界，大学生应当更好地准备自己以面对各种挑战。” **为应对这些挑战，他们需要在几个关键方面采取具体措施。** **首先，学业优异仍是基础。** 学生应掌握专业知识，并与新技术保持同步。例如，一名计算机科学专业的学生如果尽早学习人工智能，可能会在求职中获得优势。**此外，软技能与硬技能同样重要。** 沟通、团队合作和时间管理有助于毕业生适应复杂的工作场所。他们还应该寻找实习和志愿工作以获得实践经验。这样的经历可以拓宽视野并增强竞争力。**最后但同样重要的是，心理韧性不应被忽视。** 面对失败和压力，学生可以通过锻炼、爱好和朋友的支持保持积极。**因此，只有通过提高知识、技能和品格，大学生才能将挑战转化为机遇，并建立有前途的未来。**''',
    'thinking': '''1. 开头直接使用给定句，点明竞争环境与准备的必要性。
2. 用总起句提出：在几个关键方面采取具体措施。
3. 主体分三层：学业硬实力 → 软技能与实践 → 心理韧性，并穿插计算机 / AI 的例子。
4. 结尾用 only by ... can ... 倒装总结，回应开头。
5. 篇幅控制在 150–200 词；采用一般现在时和情态动词，保持客观建议语气。原文字数由软件自动统计。''',
    'templates': [
        {'expression': 'To rise to these challenges, they need to take concrete steps in several key areas.',
         'meaning': '为应对这些挑战，他们需要在几个关键方面采取具体措施。',
         'note': '用于引出解决措施，适合“问题—对策”型作文。可替换 challenges、steps、areas 等词。'},
        {'expression': 'First and foremost, ... remains the foundation.',
         'meaning': '首先，……仍是基础。', 'note': '引出第一个分论点，强调基础或首要因素。'},
        {'expression': 'In addition, ... matter just as much as ...',
         'meaning': '此外，……与……同样重要。', 'note': '递进补充第二个分论点，说明两类因素同等重要。'},
        {'expression': 'Last but not least, ... should not be ignored.',
         'meaning': '最后但同样重要的是，……不应被忽视。', 'note': '引出最后但同样重要的分论点，使结构完整。'},
        {'expression': 'Therefore, only by ... can ...',
         'meaning': '因此，只有通过……才能……。', 'note': '结尾总结。only by 置于句首时，主句使用部分倒装。'},
        {'expression': 'Such experiences can broaden their horizons and strengthen their competitiveness.',
         'meaning': '这样的经历可以拓宽视野并增强竞争力。',
         'note': '评价经历或措施的作用，可用于实习、志愿活动、留学等话题。'},
    ],
    'collocations': [
        {'expression': 'first and foremost', 'meaning': '首先；首要的是', 'note': '引出首要分论点。'},
        {'expression': 'rise to the challenge', 'meaning': '迎接并应对挑战', 'note': '文中为 rise to these challenges。'},
        {'expression': 'take concrete steps', 'meaning': '采取具体措施', 'note': '提出可执行的对策。'},
        {'expression': 'academic excellence', 'meaning': '学业优异', 'note': '学业与教育话题。'},
        {'expression': 'keep pace with', 'meaning': '与……保持同步；跟上', 'note': 'keep pace with new technologies。'},
        {'expression': 'gain an edge', 'meaning': '获得优势', 'note': 'gain an edge in job hunting。'},
        {'expression': 'job hunting', 'meaning': '求职；找工作', 'note': '就业话题。'},
        {'expression': 'in addition', 'meaning': '此外；另外', 'note': '递进衔接。'},
        {'expression': 'just as much as', 'meaning': '与……同样（多／重要）', 'note': 'soft skills matter just as much as hard skills。'},
        {'expression': 'adapt to', 'meaning': '适应……', 'note': 'adapt to complex workplaces。'},
        {'expression': 'gain practical experience', 'meaning': '获得实践经验', 'note': '实习、志愿活动话题。'},
        {'expression': 'broaden their horizons', 'meaning': '拓宽他们的视野', 'note': '主语变化时可替换 their 为 our / your。'},
        {'expression': 'strengthen their competitiveness', 'meaning': '增强他们的竞争力', 'note': '评价措施的作用。'},
        {'expression': 'last but not least', 'meaning': '最后但同样重要的是', 'note': '引出最后一个分论点。'},
        {'expression': 'mental resilience', 'meaning': '心理韧性', 'note': '压力与成长话题。'},
        {'expression': 'stay positive', 'meaning': '保持积极', 'note': '面对失败与压力。'},
        {'expression': 'turn challenges into opportunities', 'meaning': '将挑战转化为机遇', 'note': 'turn ... into ... 表示将……变成……。'},
        {'expression': 'build a promising future', 'meaning': '创造有前途的未来', 'note': '用于展望与总结。'},
    ],
}
