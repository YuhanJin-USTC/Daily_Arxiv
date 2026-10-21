const DEFAULT_SUBSCRIBED_CATEGORIES = "__DEFAULT_CATEGORIES__";

const AI_ERROR_PLACEHOLDERS = new Set([
  'summary generation failed', 'motivation analysis unavailable',
  'method extraction failed', 'result analysis unavailable',
  'conclusion extraction failed', 'processing failed',
  'this content has not passed the compliance test and has been hidden.'
]);

function hasValidAI(ai) {
  return ai && ['tldr', 'motivation', 'method', 'result', 'conclusion'].every(field =>
    typeof ai[field] === 'string' && ai[field].trim() &&
    !AI_ERROR_PLACEHOLDERS.has(ai[field].trim().toLowerCase())
  );
}

function uniquePapers(data) {
  const byId = new Map();
  Object.keys(data).sort().forEach(category => {
    (data[category] || []).forEach(paper => {
      const id = (paper.id || paper.url).replace(/^https?:\/\/arxiv\.org\/abs\//, '').replace(/v\d+$/, '');
      const previous = byId.get(id);
      if (!previous) {
        byId.set(id, paper);
      } else {
        const preferred = paper.aiAvailable && !previous.aiAvailable ? paper : previous;
        const categories = [...new Set([...previous.category, ...paper.category])];
        const date = previous.date < paper.date ? previous.date : paper.date;
        byId.set(id, {...preferred, date, category: categories, allCategories: categories});
      }
    });
  });
  return [...byId.values()];
}

function papersForCategory(data, category) {
  const papers = uniquePapers(data);
  return category === 'all' ? papers : papers.filter(paper =>
    (paper.allCategories || paper.category || []).includes(category)
  );
}

function parseJsonlData(jsonlText, date) {
  const result = {};
  
  const lines = jsonlText.trim().split('\n');
  
  lines.forEach(line => {
    try {
      const paper = JSON.parse(line);
      
      if (!paper.categories) {
        return;
      }
      
      let allCategories = Array.isArray(paper.categories) ? paper.categories : [paper.categories];
      
      const primaryCategory = allCategories[0];
      
      if (!result[primaryCategory]) {
        result[primaryCategory] = [];
      }
      
      const aiAvailable = Boolean(hasValidAI(paper.AI));
      const summary = aiAvailable ? paper.AI.tldr : (paper.summary || 'Abstract unavailable');
      
      result[primaryCategory].push({
        title: paper.title,
        url: paper.abs || paper.pdf || `https://arxiv.org/abs/${paper.id}`,
        authors: Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors,
        category: allCategories,
        allCategories: allCategories,
        aiAvailable: aiAvailable,
        summary: summary,
        details: paper.summary || '',
        date: date,
        id: paper.id,
        motivation: aiAvailable ? paper.AI.motivation : '',
        method: aiAvailable ? paper.AI.method : '',
        result: aiAvailable ? paper.AI.result : '',
        conclusion: aiAvailable ? paper.AI.conclusion : '',
        code_url: paper.code_url || '',
        code_stars: paper.code_stars || 0,
        code_last_update: paper.code_last_update || ''
      });
    } catch (error) {
      console.error('解析JSON行失败:', error, line);
    }
  });
  
  return result;
}

// 获取所有类别并按偏好排序
function getAllCategories(data, subscribedCategories) {
  const papers = uniquePapers(data);
  const configured = Array.isArray(subscribedCategories) ? subscribedCategories : DEFAULT_SUBSCRIBED_CATEGORIES;
  const categories = Array.isArray(configured) ? [...new Set(configured)] : [];
  const categoryCounts = Object.fromEntries(categories.map(category => [category, 0]));
  papers.forEach(paper => {
    new Set(paper.allCategories || paper.category || []).forEach(category => {
      if (Object.hasOwn(categoryCounts, category)) categoryCounts[category]++;
    });
  });
  return {
    sortedCategories: categories,
    categoryCounts,
    totalCount: papers.length
  };
}

