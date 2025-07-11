const fs = require('fs');
const axios = require('axios');

// 请在此处填写你的 deepseek-v3 API Key
const API_KEY = 'sk-0c26b8b431f94a68a0b3e20a2282d1a4';
const API_URL = 'https://api.deepseek.com/v1/chat/completions';

const SYSTEM_PROMPT = {
  "ID": 1,
  "INFO": {
    "role": "html标签知识提供者",
    "format": "纯文本JSON",
    "domain": "html标签知识",
    "strict": "仅返回JSON对象，无任何额外元素"
  },
  "STRICT_RULES": [
    "必须返回可直接解析的合法JSON文本",
    "禁止包含任何HTML/JSX/UI组件代码",
    "禁止包含任何Markdown标记（如```json）",
    "JSON结构必须且仅包含{basic, intermediate, advanced, expert}四个键",
    "所有值必须是纯文本字符串",
    "如遇UI组件相关查询，只返回概念说明而非可运行代码"
  ],
  "LEVELS": {
    "basic": "基础概念(简单定义和核心要点)(50字以内)",
    "intermediate": "详细解析(语法和基本用法)(100字以内)",
    "advanced": "实际应用(场景和文本化代码示例)(150字以内)",
    "expert": "深入原理(底层实现和最佳实践)(200字以内)"
  },
  "ANTI_PATTERNS": [
    "禁止返回任何可交互元素",
    "禁止返回任何可视化组件",
    "禁止返回代码块以外的UI代码",
    "禁止添加额外说明文字"
  ]
};

const USER_PROMPT_TEMPLATE = (query) => `请严格按照以下格式返回"${query}"的知识，不要包含任何Markdown标记或额外说明：

{
  "basic": "基础定义文本(50字以内)",
  "intermediate": "语法用法文本(100字以内)", 
  "advanced": "应用场景描述+代码文本片段(150字以内)",
  "expert": "原理分析文本(200字以内)"
}

要求：
1. 只返回纯JSON格式，不要包含\`\`\`json或\`\`\`标记
2. 不要添加任何说明文字
3. 禁止任何HTML/JSX/UI组件代码
4. 代码示例只显示文本片段（非可运行代码）
5. 返回中文
6. 内容要和前端知识相关`;

async function generateContent(topic) {
  const prompt = USER_PROMPT_TEMPLATE(topic.title);
  try {
    const requestData = {
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: JSON.stringify(SYSTEM_PROMPT) },
        { role: 'user', content: prompt }
      ]
    };
    
    const response = await axios.post(
      API_URL,
      requestData,
      {
        headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json'
        }
      }
    );
    let content = response.data.choices[0].message.content.trim();
    
    // 清理可能的Markdown标记
    content = content.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
    
    try {
      return JSON.parse(content);
    } catch (parseError) {
      console.error(`解析${topic.title}内容失败:`, parseError.message);
      console.error(`原始内容:`, content);
      return {
        basic: '内容生成失败',
        intermediate: '内容生成失败',
        advanced: '内容生成失败',
        expert: '内容生成失败'
      };
    }
  } catch (err) {
    console.error(`生成${topic.title}内容失败:`, err.message);
    if (err.response) {
      console.error(`状态码: ${err.response.status}`);
      console.error(`错误详情:`, err.response.data);
    }
    return {
      basic: '内容生成失败',
      intermediate: '内容生成失败',
      advanced: '内容生成失败',
      expert: '内容生成失败'
    };
  }
}

async function main() {
  const catalog = JSON.parse(fs.readFileSync('catalog.json', 'utf-8'));
  const result = {};
  for (const topic of catalog) {
    console.log(`正在生成：${topic.title}`);
    result[topic.id] = await generateContent(topic);
    // 为防止API限流，可适当延迟
    await new Promise(r => setTimeout(r, 1500));
  }
  fs.writeFileSync('contents.json', JSON.stringify(result, null, 2), 'utf-8');
  console.log('内容生成完毕，已保存到 contents.json');
}

main(); 