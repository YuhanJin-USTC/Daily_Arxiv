let currentDate = '';
let selectedStartDate = '';
let selectedEndDate = '';
let paperRequest = 0;
let openPaperId = null;
let availableDates = [];
let currentView = 'grid'; // 'grid' 或 'list'
let currentCategory = 'all';
let paperData = {};
let flatpickrInstance = null;
let isRangeMode = false;
let activeKeywords = []; // 存储激活的关键词
let userKeywords = []; // 存储用户的关键词
let activeAuthors = []; // 存储激活的作者
let userAuthors = []; // 存储用户的作者
let currentPaperIndex = 0; // 当前查看的论文索引
let currentFilteredPapers = []; // 当前过滤后的论文列表
let textSearchQuery = ''; // 实时文本搜索查询
let previousActiveKeywords = null; // 文本搜索激活时，暂存之前的关键词激活集合
let previousActiveAuthors = null; // 文本搜索激活时，暂存之前的作者激活集合

// 加载用户的关键词设置
function loadUserKeywords() {
  const savedKeywords = readPreference('preferredKeywords', true);
  if (savedKeywords) {
    try {
      userKeywords = JSON.parse(savedKeywords);
      // 默认激活所有关键词
      activeKeywords = [...userKeywords];
    } catch (error) {
      console.error('解析关键词失败:', error);
      userKeywords = [];
      activeKeywords = [];
    }
  } else {
    userKeywords = [];
    activeKeywords = [];
  }
  
  // renderKeywordTags();
  renderFilterTags();
}

// 加载用户的作者设置
function loadUserAuthors() {
  const savedAuthors = readPreference('preferredAuthors', true);
  if (savedAuthors) {
    try {
      userAuthors = JSON.parse(savedAuthors);
      // 默认激活所有作者
      activeAuthors = [...userAuthors];
    } catch (error) {
      console.error('解析作者失败:', error);
      userAuthors = [];
      activeAuthors = [];
    }
  } else {
    userAuthors = [];
    activeAuthors = [];
  }
  
  renderFilterTags();
}

// 渲染过滤标签（作者和关键词）
function renderFilterTags() {
  const filterTagsElement = document.getElementById('filterTags');
  const filterContainer = document.querySelector('.filter-label-container');
  
  // 如果没有作者和关键词，仅隐藏标签区域，保留容器（以显示搜索按钮）
  if ((!userAuthors || userAuthors.length === 0) && (!userKeywords || userKeywords.length === 0)) {
    filterContainer.style.display = 'flex';
    if (filterTagsElement) {
      filterTagsElement.style.display = 'none';
      filterTagsElement.innerHTML = '';
    }
    return;
  }
  
  filterContainer.style.display = 'flex';
  if (filterTagsElement) {
    filterTagsElement.style.display = 'flex';
  }
  filterTagsElement.innerHTML = '';
  
  // 先添加作者标签
  if (userAuthors && userAuthors.length > 0) {
    userAuthors.forEach(author => {
      const tagElement = document.createElement('span');
      tagElement.className = `category-button author-button ${activeAuthors.includes(author) ? 'active' : ''}`;
      tagElement.textContent = author;
      tagElement.dataset.author = author;
      tagElement.title = "匹配作者姓名";
      
      tagElement.addEventListener('click', () => {
        toggleAuthorFilter(author);
      });
      
      filterTagsElement.appendChild(tagElement);
      
      // 添加出现动画后移除动画类
      if (!activeAuthors.includes(author)) {
        tagElement.classList.add('tag-appear');
        setTimeout(() => {
          tagElement.classList.remove('tag-appear');
        }, 300);
      }
    });
  }
  
  // 再添加关键词标签
  if (userKeywords && userKeywords.length > 0) {
    userKeywords.forEach(keyword => {
      const tagElement = document.createElement('span');
      tagElement.className = `category-button keyword-button ${activeKeywords.includes(keyword) ? 'active' : ''}`;
      tagElement.textContent = keyword;
      tagElement.dataset.keyword = keyword;
      tagElement.title = "匹配标题和摘要中的关键词";
      
      tagElement.addEventListener('click', () => {
        toggleKeywordFilter(keyword);
      });
      
      filterTagsElement.appendChild(tagElement);
      
      // 添加出现动画后移除动画类
      if (!activeKeywords.includes(keyword)) {
        tagElement.classList.add('tag-appear');
        setTimeout(() => {
          tagElement.classList.remove('tag-appear');
        }, 300);
      }
    });
  }
}

// 切换关键词过滤
function toggleKeywordFilter(keyword) {
  const index = activeKeywords.indexOf(keyword);
  
  if (index === -1) {
    // 激活该关键词
    activeKeywords.push(keyword);
  } else {
    // 取消激活该关键词
    activeKeywords.splice(index, 1);
  }
  
  // 更新关键词标签UI
  const keywordTags = document.querySelectorAll('[data-keyword]');
  keywordTags.forEach(tag => {
    if (tag.dataset.keyword === keyword) {
      // 先移除上一次可能的高亮动画
      tag.classList.remove('tag-highlight');
      
      // 添加/移除激活状态
      tag.classList.toggle('active', activeKeywords.includes(keyword));
      
      // 添加高亮动画
      setTimeout(() => {
        tag.classList.add('tag-highlight');
      }, 10);
      
      // 移除高亮动画
      setTimeout(() => {
        tag.classList.remove('tag-highlight');
      }, 1000);
    }
  });
  
  // 重新渲染论文列表
  renderPapers();
}


// 切换作者过滤
function toggleAuthorFilter(author) {
  const index = activeAuthors.indexOf(author);
  
  if (index === -1) {
    // 激活该作者
    activeAuthors.push(author);
  } else {
    // 取消激活该作者
    activeAuthors.splice(index, 1);
  }
  
  // 更新作者标签UI
  const authorTags = document.querySelectorAll('[data-author]');
  authorTags.forEach(tag => {
    if (tag.dataset.author === author) {
      // 先移除上一次可能的高亮动画
      tag.classList.remove('tag-highlight');
      
      // 添加/移除激活状态
      tag.classList.toggle('active', activeAuthors.includes(author));
      
      // 添加高亮动画
      setTimeout(() => {
        tag.classList.add('tag-highlight');
      }, 10);
      
      // 移除高亮动画
      setTimeout(() => {
        tag.classList.remove('tag-highlight');
      }, 1000);
    }
  });
  
  // 重新渲染论文列表
  renderPapers();
}

document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  initLanguageSelector(() => {
    if (selectedStartDate) loadSelectedPapers(selectedStartDate, selectedEndDate);
  });
  
  fetchGitHubStats();
  
  // 加载用户关键词
  loadUserKeywords();
  
  // 加载用户作者
  loadUserAuthors();
  
  fetchAvailableDates().then(() => {
    if (availableDates.length > 0) {
      loadPapersByDate(availableDates[0]);
    }
  });
});

async function fetchGitHubStats() {
  try {
    const response = await fetch(DATA_CONFIG.getRepositoryApiUrl());
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const starCount = data.stargazers_count;
    const forkCount = data.forks_count;
    
    document.getElementById('starCount').textContent = starCount;
    document.getElementById('forkCount').textContent = forkCount;
  } catch (error) {
    console.error('获取GitHub统计数据失败:', error);
    document.getElementById('starCount').textContent = '?';
    document.getElementById('forkCount').textContent = '?';
  }
}

function initEventListeners() {
  // 日期选择器相关的事件监听
  const calendarButton = document.getElementById('calendarButton');
  calendarButton.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleDatePicker();
  });
  
  const datePickerModal = document.querySelector('.date-picker-modal');
  datePickerModal.addEventListener('click', (event) => {
    if (event.target === datePickerModal) {
      toggleDatePicker();
    }
  });
  
  const datePickerContent = document.querySelector('.date-picker-content');
  datePickerContent.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  document.getElementById('dateRangeMode').addEventListener('change', toggleRangeMode);
  
  // 其他原有的事件监听器
  document.getElementById('closeModal').addEventListener('click', closeModal);
  
  document.querySelector('.paper-modal').addEventListener('click', (event) => {
    const modal = document.querySelector('.paper-modal');
    const pdfContainer = modal.querySelector('.pdf-container');
    
    // 如果点击的是模态框背景
    if (event.target === modal) {
      // 检查PDF是否处于放大状态
      if (pdfContainer && pdfContainer.classList.contains('expanded')) {
        // 如果PDF是放大的，先将其恢复正常大小
        const expandButton = modal.querySelector('.pdf-expand-btn');
        if (expandButton) {
          togglePdfSize(expandButton);
        }
        // 阻止事件继续传播，防止关闭整个模态框
        event.stopPropagation();
      } else {
        // 如果PDF不是放大状态，则关闭整个模态框
        closeModal();
      }
    }
  });
  
  // 添加键盘事件监听 - Esc 键关闭模态框，左右箭头键切换论文，R 键显示随机论文
  document.addEventListener('keydown', (event) => {
    // 检查是否有输入框或文本区域处于焦点状态
    const activeElement = document.activeElement;
    const isInputFocused = activeElement && (
      activeElement.tagName === 'INPUT' || 
      activeElement.tagName === 'TEXTAREA' || 
      activeElement.isContentEditable
    );
    
    if (event.key === 'Escape') {
      const paperModal = document.getElementById('paperModal');
      const datePickerModal = document.getElementById('datePickerModal');
      
      // 关闭论文模态框
      if (paperModal.classList.contains('active')) {
        closeModal();
      }
      // 关闭日期选择器模态框
      else if (datePickerModal.classList.contains('active')) {
        toggleDatePicker();
      }
    }
    // 左右箭头键导航论文（仅在论文模态框打开时）
    else if (!isInputFocused && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
      const paperModal = document.getElementById('paperModal');
      if (paperModal.classList.contains('active')) {
        event.preventDefault(); // 防止页面滚动
        
        if (event.key === 'ArrowLeft') {
          navigateToPreviousPaper();
        } else if (event.key === 'ArrowRight') {
          navigateToNextPaper();
        }
      }
    }
    // space 键显示随机论文（在没有输入框焦点且日期选择器未打开时）
    else if (event.key === ' ' || event.key === 'Spacebar') {
      const paperModal = document.getElementById('paperModal');
      const datePickerModal = document.getElementById('datePickerModal');
      
      // 只有在没有输入框焦点且日期选择器没有打开时才触发
      // 现在允许在论文模态框打开时也能使用R键切换到随机论文
      if (!isInputFocused && !activeElement?.closest('button, a, select') && !datePickerModal.classList.contains('active')) {
        event.preventDefault(); // 防止页面刷新
        event.stopPropagation(); // 阻止事件冒泡
        showRandomPaper();
      }
    }
  });
  
  // 添加鼠标滚轮横向滚动支持
  initCategoryNavigation();
  const keywordScroll = document.querySelector('.keyword-scroll');
  const authorScroll = document.querySelector('.author-scroll');
  
  // 为关键词滚动添加鼠标滚轮事件
  if (keywordScroll) {
    keywordScroll.addEventListener('wheel', function(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        this.scrollLeft += e.deltaY;
      }
    });
  }
  
  // 为作者滚动添加鼠标滚轮事件
  if (authorScroll) {
    authorScroll.addEventListener('wheel', function(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        this.scrollLeft += e.deltaY;
      }
    });
  }

  // 其他事件监听器...
  const categoryButtons = document.querySelectorAll('.category-button');
  categoryButtons.forEach(button => {
    button.addEventListener('click', () => {
      const category = button.dataset.category;
      filterByCategory(category);
    });
  });

  // 回到顶部按钮：滚动显示/隐藏 + 点击回到顶部
  const backToTopButton = document.getElementById('backToTop');
  if (backToTopButton) {
    const updateBackToTopVisibility = () => {
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
      if (scrollTop > 300) {
        backToTopButton.classList.add('visible');
      } else {
        backToTopButton.classList.remove('visible');
      }
    };

    // 初始判断一次（防止刷新在中部时不显示）
    updateBackToTopVisibility();
    window.addEventListener('scroll', updateBackToTopVisibility, { passive: true });

    backToTopButton.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // 文本搜索：放大镜切换显示输入框
  const searchToggle = document.getElementById('textSearchToggle');
  const searchWrapper = document.querySelector('#textSearchContainer .search-input-wrapper');
  const searchInput = document.getElementById('textSearchInput');
  const searchClear = document.getElementById('textSearchClear');

  if (searchToggle && searchWrapper && searchInput && searchClear) {
    searchToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      searchWrapper.style.display = 'flex';
      searchInput.focus();
    });

    // 输入时更新查询并重新渲染
    const handleInput = () => {
      const value = searchInput.value.trim();
      textSearchQuery = value;
      // 有非空文本时：通过切换函数真正停用关键词/作者过滤，并记录之前状态
      if (textSearchQuery.length > 0) {
        if (previousActiveKeywords === null) {
          previousActiveKeywords = [...activeKeywords];
        }
        if (previousActiveAuthors === null) {
          previousActiveAuthors = [...activeAuthors];
        }
        // 逐个停用当前激活的关键词/作者
        // 注意：在遍历前复制数组，避免在切换过程中修改原数组导致遍历问题
        const keywordsToDisable = [...activeKeywords];
        const authorsToDisable = [...activeAuthors];
        keywordsToDisable.forEach(k => toggleKeywordFilter(k));
        authorsToDisable.forEach(a => toggleAuthorFilter(a));
      } else {
        // 文本删除为空，恢复之前记录的关键词/作者激活状态
        if (previousActiveKeywords && previousActiveKeywords.length > 0) {
          previousActiveKeywords.forEach(k => {
            // 若当前未激活则切换回激活
            if (!activeKeywords.includes(k)) toggleKeywordFilter(k);
          });
        }
        if (previousActiveAuthors && previousActiveAuthors.length > 0) {
          previousActiveAuthors.forEach(a => {
            if (!activeAuthors.includes(a)) toggleAuthorFilter(a);
          });
        }
        previousActiveKeywords = null;
        previousActiveAuthors = null;
        // 文本为空时自动隐藏输入框
        searchWrapper.style.display = 'none';
      }

      // 控制清除按钮显示
      searchClear.style.display = textSearchQuery.length > 0 ? 'inline-flex' : 'none';

      renderPapers();
    };

    searchInput.addEventListener('input', handleInput);

    // 清除按钮：清空文本，恢复其他过滤
    searchClear.addEventListener('click', (e) => {
      e.stopPropagation();
      searchInput.value = '';
      textSearchQuery = '';
      searchClear.style.display = 'none';
      // 恢复之前的过滤状态（如有）
      if (previousActiveKeywords && previousActiveKeywords.length > 0) {
        previousActiveKeywords.forEach(k => {
          if (!activeKeywords.includes(k)) toggleKeywordFilter(k);
        });
      }
      if (previousActiveAuthors && previousActiveAuthors.length > 0) {
        previousActiveAuthors.forEach(a => {
          if (!activeAuthors.includes(a)) toggleAuthorFilter(a);
        });
      }
      previousActiveKeywords = null;
      previousActiveAuthors = null;
      renderPapers();
      // 清空后隐藏输入框
      searchWrapper.style.display = 'none';
    });

    // 失焦时：若文本为空则隐藏输入框（保持有文本时不隐藏）
    searchInput.addEventListener('blur', () => {
      const value = searchInput.value.trim();
      if (value.length === 0) {
        searchWrapper.style.display = 'none';
      }
    });

    // 点击其他地方不隐藏输入框（需求4），因此不添加blur隐藏逻辑
  }
}

async function fetchAvailableDates() {
  try {
    const response = await fetch(DATA_CONFIG.getDataUrl('assets/file-list.txt'));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    availableDates = datesFromInventory(await response.text());
    initDatePicker();
    return availableDates;
  } catch (error) {
    console.error('Available dates unavailable:', error);
    return [];
  }
}

function initDatePicker() {
  const datepickerInput = document.getElementById('datepicker');
  
  if (flatpickrInstance) {
    flatpickrInstance.destroy();
  }
  
  // 创建可用日期的映射，用于禁用无效日期
  const enabledDatesMap = {};
  availableDates.forEach(date => {
    enabledDatesMap[date] = true;
  });
  
  // 配置 Flatpickr
  flatpickrInstance = flatpickr(datepickerInput, {
    inline: true,
    dateFormat: "Y-m-d",
    defaultDate: availableDates[0],
    enable: [
      function(date) {
        // 只启用有效日期
        const dateStr = date.getFullYear() + "-" +
                        String(date.getMonth() + 1).padStart(2, '0') + "-" +
                        String(date.getDate()).padStart(2, '0');
        // 在 availableDates[0] 之后的日期全部返回 false，否则返回 true
        return dateStr <= availableDates[0];
      }
    ],
    onChange: function(selectedDates, dateStr) {
      if (isRangeMode && selectedDates.length === 2) {
        // 处理日期范围选择
        const startDate = formatDateForAPI(selectedDates[0]);
        const endDate = formatDateForAPI(selectedDates[1]);
        loadPapersByDateRange(startDate, endDate);
        toggleDatePicker();
      } else if (!isRangeMode && selectedDates.length === 1) {
        // 处理单个日期选择
        const selectedDate = formatDateForAPI(selectedDates[0]);
        // if (availableDates.includes(selectedDate)) {
          loadPapersByDate(selectedDate);
          toggleDatePicker();
        // }
      }
    }
  });
  
  // 隐藏日期输入框
  const inputElement = document.querySelector('.flatpickr-input');
  if (inputElement) {
    inputElement.style.display = 'none';
  }
}

function formatDateForAPI(date) {
  return date.getFullYear() + "-" + 
         String(date.getMonth() + 1).padStart(2, '0') + "-" + 
         String(date.getDate()).padStart(2, '0');
}

function toggleRangeMode() {
  isRangeMode = document.getElementById('dateRangeMode').checked;
  
  if (flatpickrInstance) {
    flatpickrInstance.set('mode', isRangeMode ? 'range' : 'single');
    flatpickrInstance.clear(false);
  }
}

async function loadPapersByDate(date) {
  if (flatpickrInstance) flatpickrInstance.setDate(date, false);
  return loadSelectedPapers(date, date);
}

async function loadSelectedPapers(startDate, endDate) {
  selectedStartDate = startDate;
  selectedEndDate = endDate;
  const request = ++paperRequest;
  const language = getPreferredLanguage();
  const dates = startDate === endDate ? [startDate] :
    availableDates.filter(date => date >= startDate && date <= endDate);
  currentDate = startDate === endDate ? startDate : `${startDate} to ${endDate}`;
  document.getElementById('currentDate').textContent = startDate === endDate ? formatDate(startDate) :
    `${formatDate(startDate)} - ${formatDate(endDate)}`;
  const container = document.getElementById('paperContainer');
  container.setAttribute('aria-busy', 'true');
  container.innerHTML = '<div class="loading-container"><div class="loading-spinner"></div><p>Loading papers...</p></div>';
  try {
    const loaded = await loadPaperDates(dates, language, {includeTopics: true});
    if (request !== paperRequest) return;
    paperData = loaded;
    renderCategoryFilter(getAllCategories(paperData, DATA_CONFIG.categories));
    renderPapers();
  } catch (error) {
    if (request !== paperRequest) return;
    container.innerHTML = `<div class="loading-container"><p>Loading data failed. Please retry.</p><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    if (request === paperRequest) container.setAttribute('aria-busy', 'false');
  }
}

function updateCategoryNavigation() {
  const list = document.getElementById('categoryList');
  const prev = document.getElementById('categoryPrev');
  const next = document.getElementById('categoryNext');
  const available = list.clientWidth + prev.offsetWidth + next.offsetWidth;
  prev.hidden = next.hidden = list.scrollWidth <= available + 1;
  prev.disabled = list.scrollLeft <= 1;
  next.disabled = list.scrollLeft + list.clientWidth >= list.scrollWidth - 1;
}

function revealActiveCategory(list) {
  const active = list.querySelector('.category-button.active');
  if (!active) return;
  const start = active.offsetLeft - list.offsetLeft;
  const end = start + active.offsetWidth;
  if (start < list.scrollLeft) list.scrollLeft = start;
  else if (end > list.scrollLeft + list.clientWidth) list.scrollLeft = end - list.clientWidth;
}

function initCategoryNavigation() {
  const list = document.getElementById('categoryList');
  const prev = document.getElementById('categoryPrev');
  const next = document.getElementById('categoryNext');
  const step = direction => list.scrollBy({left: direction * list.clientWidth * 0.8, behavior: 'smooth'});
  prev.addEventListener('click', () => step(-1));
  next.addEventListener('click', () => step(1));
  list.addEventListener('scroll', updateCategoryNavigation, {passive: true});
  list.addEventListener('wheel', event => {
    if (event.ctrlKey || event.shiftKey || !event.deltaY || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
    const atEdge = event.deltaY < 0 ? list.scrollLeft <= 0 :
      list.scrollLeft >= list.scrollWidth - list.clientWidth - 1;
    if (atEdge || list.scrollWidth <= list.clientWidth) return;
    event.preventDefault();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? list.clientWidth : 1;
    list.scrollLeft += event.deltaY * unit;
  }, {passive: false});
  new ResizeObserver(updateCategoryNavigation).observe(list.parentElement);
  document.fonts.ready.then(updateCategoryNavigation);
}

function renderCategoryFilter(categories) {
  const container = document.querySelector('.category-scroll');
  const { sortedCategories, categoryCounts, totalCount = 0 } = categories;
  const totalPapers = totalCount;

  container.innerHTML = `
    <button class="category-button ${currentCategory === 'all' ? 'active' : ''}" data-category="all" aria-pressed="${currentCategory === 'all'}">All<span class="category-count">${totalPapers}</span></button>
  `;
  
  sortedCategories.forEach(category => {
    const count = categoryCounts[category];
    const button = document.createElement('button');
    button.className = `category-button ${category === currentCategory ? 'active' : ''}`;
    button.innerHTML = `${escapeHtml(category)}<span class="category-count">${count}</span>`;
    button.dataset.category = category;
    button.setAttribute('aria-pressed', String(category === currentCategory));
    button.addEventListener('click', () => {
      filterByCategory(category);
    });
    
    container.appendChild(button);
  });
  
  document.querySelector('.category-button[data-category="all"]').addEventListener('click', () => {
    filterByCategory('all');
  });
  updateCategoryNavigation();
  revealActiveCategory(container);
}

function filterByCategory(category) {
  currentCategory = category;
  
  document.querySelectorAll('#categoryList [data-category]').forEach(button => {
    button.classList.toggle('active', button.dataset.category === category);
    button.setAttribute('aria-pressed', String(button.dataset.category === category));
  });
  revealActiveCategory(document.getElementById('categoryList'));
  
  // 保持当前激活的过滤标签
  renderFilterTags();
  
  // 重置页面滚动条到顶部
  window.scrollTo({
    top: 0,
    behavior: 'smooth'
  });
  
  renderPapers();
}

function formatAuthorsForCard(authorsString, authorTerms = [], researcherMatches = []) {
  return formatPaperAuthors({authors: authorsString, researcherMatches}, authorTerms, true);
}

function matchReasons(paper) {
  const reasons = [];
  const query = textSearchQuery.trim();
  if (query) {
    const searchable = [paper.title, paper.authors, paper.category.join(', '), paper.summary,
      paper.details, paper.motivation, paper.method, paper.result, paper.conclusion,
      ...(paper.topics?.keywords || [])].join(' ').toLowerCase();
    if (searchable.includes(query.toLowerCase())) reasons.push(`文本: ${query}`);
  }
  const titleAndSummary = `${paper.title} ${paper.summary}`.toLowerCase();
  const keywords = activeKeywords.filter(term => titleAndSummary.includes(term.toLowerCase()));
  const authorText = String(paper.authors || '').toLowerCase();
  const authors = activeAuthors.filter(term => authorText.includes(term.toLowerCase()));
  if (keywords.length) reasons.push(`关键词: ${keywords.join(', ')}`);
  if (authors.length) reasons.push(`作者: ${authors.join(', ')}`);
  return reasons;
}

function rankedPapers(papers) {
  return papers.map(paper => {
    const matchReason = matchReasons(paper);
    const researcherKind = ['reliable', 'suspected'].find(kind =>
      paper.researcherMatches.some(match => match.kind === kind));
    const priority = {reliable: 0, suspected: 1}[researcherKind] ??
      (paper.topics?.laser_plasma_keywords.length ? 2 : 3);
    return {...paper, matchReason, isMatched: Boolean(matchReason.length), researcherKind, priority};
  }).sort((a, b) => Number(b.isMatched) - Number(a.isMatched) || a.priority - b.priority);
}

function formatPaperKeywords(paper) {
  if (!paper.topics) return '';
  const chips = paper.topics.keywords.map(keyword => {
    const relevant = paper.topics.laser_plasma_keywords.includes(keyword);
    const label = relevant ? `Laser–plasma keyword: ${keyword}` : keyword;
    return `<span class="paper-keyword${relevant ? ' laser-plasma-keyword' : ''}" role="listitem" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${escapeHtml(keyword)}</span>`;
  });
  return `<div class="paper-keywords" role="list" aria-label="Paper keywords">${chips.join('')}</div>`;
}

function renderPapers() {
  const container = document.getElementById('paperContainer');
  container.innerHTML = '';
  container.className = `paper-container ${currentView === 'list' ? 'list-view' : ''}`;
  const filteredPapers = rankedPapers(papersForCategory(paperData, currentCategory));
  currentFilteredPapers = filteredPapers;
  if (openPaperId !== null) {
    const index = filteredPapers.findIndex(paper => normalizePaperId(paper.id || paper.url) === openPaperId);
    if (index === -1) {
      closeModal();
    } else {
      const body = document.getElementById('modalBody');
      const scroll = body.scrollTop;
      currentPaperIndex = index;
      showPaperDetails(filteredPapers[index], index + 1);
      body.scrollTop = scroll;
    }
  }

  if (filteredPapers.length === 0) {
    container.innerHTML = `
      <div class="loading-container">
        <p>No paper found.</p>
      </div>
    `;
    return;
  }
  
  filteredPapers.forEach((paper, index) => {
    const paperCard = document.createElement('div');
    const classes = ['paper-card'];
    if (paper.isMatched) classes.push('matched-paper');
    if (paper.researcherKind) classes.push(`researcher-card-${paper.researcherKind}`);
    paperCard.className = classes.join(' ');
    paperCard.dataset.id = paper.id || paper.url;
    
    if (paper.isMatched) {
      // 添加匹配原因提示
      paperCard.title = `匹配: ${paper.matchReason.join(' | ')}`;
    }
    
    const categoryTags = paper.allCategories ? 
      paper.allCategories.map(cat => `<span class="category-tag">${escapeHtml(cat)}</span>`).join('') :
      `<span class="category-tag">${escapeHtml(paper.category)}</span>`;
    
    // 组合需要高亮的词：关键词 + 文本搜索
    const titleSummaryTerms = [];
    if (activeKeywords.length > 0) {
      titleSummaryTerms.push(...activeKeywords);
    }
    if (textSearchQuery && textSearchQuery.trim().length > 0) {
      titleSummaryTerms.push(textSearchQuery.trim());
    }

    // 高亮标题和摘要（关键词与文本搜索）
    const highlightedTitle = titleSummaryTerms.length > 0 
      ? highlightMatches(paper.title, titleSummaryTerms, 'keyword-highlight') 
      : escapeHtml(paper.title);
    const highlightedSummary = titleSummaryTerms.length > 0 
      ? highlightMatches(paper.summary, titleSummaryTerms, 'keyword-highlight') 
      : escapeHtml(paper.summary);

    // 高亮作者（作者过滤 + 文本搜索）
    const authorTerms = [];
    if (activeAuthors.length > 0) authorTerms.push(...activeAuthors);
    if (textSearchQuery && textSearchQuery.trim().length > 0) authorTerms.push(textSearchQuery.trim());
    
    // 格式化作者列表（应用截断规则和高亮）
    const formattedAuthors = formatPaperAuthors(paper, authorTerms, true);
    
    // 构建 GitHub 按钮 HTML
    // let githubHtml = '';
    // if (paper.code_url) {
    //   const stars = paper.code_stars ? `<span class="github-stars">★ ${paper.code_stars}</span>` : '';
    //   const isHot = paper.code_stars > 100;
      
    //   githubHtml = `
    //     <a href="${paper.code_url}" target="_blank" class="github-link" title="View Code" onclick="event.stopPropagation()">
    //       <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor" style="vertical-align: text-bottom; margin-right: 4px;">
    //         <path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
    //       </svg>
    //       Code ${stars}
    //       ${isHot ? '<span class="hot-icon">🔥</span>' : ''}
    //     </a>
    //   `;
    // }

    paperCard.innerHTML = `
      <div class="paper-card-index">${index + 1}</div>
      ${paper.isMatched ? `<div class="match-badge" role="img" aria-label="${escapeHtml(paperCard.title)}" title="${escapeHtml(paperCard.title)}"></div>` : ''}
      <div class="paper-card-header">
        <h3 class="paper-card-title">${highlightedTitle}</h3>
        <p class="paper-card-authors">${formattedAuthors}</p>
        <div class="paper-card-categories">
          ${categoryTags}
        </div>
        ${formatPaperKeywords(paper)}
      </div>
      <div class="paper-card-body">
        ${!paper.aiAvailable ? `<p class="ai-summary-status">${escapeHtml(aiUnavailableMessage(paper))}</p>` : ''}
        <p class="paper-card-summary">${highlightedSummary}</p>
        <div class="paper-card-footer">
          <div class="footer-left">
            <span class="paper-card-date">${formatDate(paper.date)}</span>
          </div>
          <button type="button" class="paper-card-link" aria-label="Details for ${escapeHtml(paper.title)}">Details</button>
        </div>
      </div>
    `;
    
    paperCard.addEventListener('click', () => {
      currentPaperIndex = index; // 记录当前点击的论文索引
      showPaperDetails(paper, index + 1);
    });
    
    container.appendChild(paperCard);
  });
}

function paperPdfSource(value) {
  const path = /^https?:\/\/(?:www\.)?arxiv\.org\/(?:abs|pdf)\/([^?#\s]+)(?:[?#][^\s]*)?$/i.exec(value);
  if (!path) return null;
  const id = path[1].replace(/\.pdf$/i, '');
  if (id.length > 80) return null;
  const modern = /^(\d{2})(0[1-9]|1[0-2])\.\d{4,5}(?:v[1-9]\d*)?$/.exec(id);
  const legacy = /^[a-z][a-z.-]*\/(\d{2})(0[1-9]|1[0-2])\d{3}(?:v[1-9]\d*)?$/i.exec(id);
  if (!modern && !legacy) return null;
  const [, yy, month] = modern || legacy;
  const year = (legacy && Number(yy) >= 91 ? 1900 : 2000) + Number(yy);
  const yearMonth = year * 100 + Number(month);
  if (modern ? yearMonth < 200704 : yearMonth < 199108 || yearMonth > 200703) return null;
  return {id, year, url: `https://arxiv.org/pdf/${id}`};
}

function paperPdfNames(paper, source) {
  const clean = value => String(value || '').normalize('NFC')
    .replace(/[<>:"/\\|?*\s\p{Cc}\p{Cs}\u202a-\u202e\u2066-\u2069]+/gu, '-')
    .replace(/^-+|-+$/g, '');
  const author = clean(paper.authorList?.[0]) || 'Unknown-author';
  const title = clean(paper.title) || clean(source.id);
  const stem = `${source.year}-ArXiv-${author}-${title}`;
  const full = stem + '.pdf';
  const encoder = new TextEncoder();
  if (encoder.encode(full).length <= 255) return {full, download: full};

  const suffix = `-${clean(source.id)}.pdf`;
  let available = 255 - encoder.encode(suffix).length;
  let prefix = '';
  for (const character of stem) {
    available -= encoder.encode(character).length;
    if (available < 0) break;
    prefix += character;
  }
  return {full, download: prefix.replace(/[. -]+$/, '') + suffix};
}

function bindPdfDownload(source, names) {
  const button = document.getElementById('downloadPaperPdf');
  const status = document.getElementById('pdfDownloadStatus');
  const fallback = document.getElementById('pdfDownloadFallback');
  const suggested = document.getElementById('suggestedPdfName');
  suggested.value = names.full;
  suggested.addEventListener('focus', () => suggested.select());
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    status.textContent = 'Downloading PDF…';
    try {
      const response = await fetch(source.url, {credentials: 'omit', redirect: 'error'});
      if (!response.ok) throw new Error('PDF request failed');
      const blob = await response.blob();
      if (await blob.slice(0, 5).text() !== '%PDF-') throw new Error('Invalid PDF');
      if (!button.isConnected || openPaperId === null) return;

      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      try {
        link.href = url;
        link.download = names.download;
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      }
      status.textContent = names.download === names.full ? 'Download started.' : 'Download started with a shortened filename.';
    } catch {
      fallback.hidden = false;
      status.textContent = 'Download unavailable. Open the PDF and save it using the suggested filename.';
    } finally {
      button.disabled = false;
    }
  });
}

function bindChatGPT(paper, source) {
  const link = document.getElementById('chatgptLink');
  const feedback = document.getElementById('chatgptFeedback');
  const status = document.getElementById('chatgptStatus');
  const field = document.getElementById('chatgptPrompt');
  feedback.hidden = field.hidden = true;
  const request = getPreferredLanguage() === 'Chinese'
    ? '请阅读这篇论文，用中文概括研究问题、方法、主要结果和局限。若无法读取全文，请说明可用来源。'
    : 'Read this paper and summarize its research question, methods, main results and limitations in English. If you cannot access the full text, identify the sources you used.';
  const prompt = [request, paper.title, ...(source ? [`https://arxiv.org/abs/${source.id}`, source.url] : [])].join('\n\n');
  field.value = prompt;
  const copyPrompt = async () => {
    let copied = false;
    try {
      await navigator.clipboard.writeText(prompt);
      copied = true;
    } catch {
      // Browsers may deny clipboard access when opening a new tab.
    }
    if (link.onclick !== copyPrompt) return;
    feedback.hidden = false;
    field.hidden = copied;
    status.textContent = copied ? 'Prompt copied. Paste it into your ChatGPT chat.' : 'Copy this prompt and paste it into ChatGPT.';
    if (!copied) field.select();
  };
  link.onclick = copyPrompt;
}

function showPaperDetails(paper, paperIndex) {
  openPaperId = normalizePaperId(paper.id || paper.url);
  const modal = document.getElementById('paperModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const paperLink = document.getElementById('paperLink');
  const pdfLink = document.getElementById('pdfLink');
  const htmlLink = document.getElementById('htmlLink');
  const pdfSource = paperPdfSource(paper.url);
  const pdfNames = pdfSource && paperPdfNames(paper, pdfSource);
  
  // 重置模态框的滚动位置
  modalBody.scrollTop = 0;
  
  // 组合高亮词：关键词 + 文本搜索
  const modalTitleTerms = [];
  if (activeKeywords.length > 0) modalTitleTerms.push(...activeKeywords);
  if (textSearchQuery && textSearchQuery.trim().length > 0) modalTitleTerms.push(textSearchQuery.trim());
  // 高亮标题
  const highlightedTitle = modalTitleTerms.length > 0 
    ? highlightMatches(paper.title, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.title);
  
  // 在标题前添加索引号
  modalTitle.innerHTML = paperIndex ? `<span class="paper-index-badge">${paperIndex}</span> ${highlightedTitle}` : highlightedTitle;
  
  const abstractText = paper.details || '';
  
  const categoryDisplay = paper.allCategories ? 
    paper.allCategories.join(', ') : 
    paper.category;
  
  // 高亮作者（作者过滤 + 文本搜索）
  const modalAuthorTerms = [];
  if (activeAuthors.length > 0) modalAuthorTerms.push(...activeAuthors);
  if (textSearchQuery && textSearchQuery.trim().length > 0) modalAuthorTerms.push(textSearchQuery.trim());
  const highlightedAuthors = formatPaperAuthors(paper, modalAuthorTerms);

  // 高亮摘要（关键词 + 文本搜索）
  const highlightedSummary = modalTitleTerms.length > 0 
    ? highlightMatches(paper.summary, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.summary);
  
  // 高亮详情（Abstract/details）
  const highlightedAbstract = modalTitleTerms.length > 0 
    ? highlightMatches(abstractText, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(abstractText);
  
  // 高亮其他部分（如果存在且是摘要的一部分）
  const highlightedMotivation = paper.motivation && modalTitleTerms.length > 0 
    ? highlightMatches(paper.motivation, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.motivation);
  
  const highlightedMethod = paper.method && modalTitleTerms.length > 0 
    ? highlightMatches(paper.method, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.method);
  
  const highlightedResult = paper.result && modalTitleTerms.length > 0 
    ? highlightMatches(paper.result, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.result);
  
  const highlightedConclusion = paper.conclusion && modalTitleTerms.length > 0 
    ? highlightMatches(paper.conclusion, modalTitleTerms, 'keyword-highlight') 
    : escapeHtml(paper.conclusion);
  
  // 判断是否需要显示高亮说明
  const showHighlightLegend = activeKeywords.length > 0 || activeAuthors.length > 0;
  
  // 添加匹配标记
  const matchedPaperClass = paper.isMatched ? 'matched-paper-details' : '';
  
  const modalContent = `
    <div class="paper-details ${matchedPaperClass}">
      <p><strong>Authors: </strong>${highlightedAuthors}</p>
      <p><strong>Categories: </strong>${escapeHtml(categoryDisplay)}</p>
      <p><strong>Date: </strong>${formatDate(paper.date)}</p>
      ${formatPaperKeywords(paper)}
      
      
      ${!paper.aiAvailable ? `<p class="ai-summary-status">${escapeHtml(aiUnavailableMessage(paper))}</p>` : ''}
      <h3>${paper.aiAvailable ? 'TL;DR' : 'Original abstract'}</h3>
      <p>${highlightedSummary}</p>
      
      <div class="paper-sections">
        ${paper.motivation ? `<div class="paper-section"><h4>Motivation</h4><p>${highlightedMotivation}</p></div>` : ''}
        ${paper.method ? `<div class="paper-section"><h4>Method</h4><p>${highlightedMethod}</p></div>` : ''}
        ${paper.result ? `<div class="paper-section"><h4>Result</h4><p>${highlightedResult}</p></div>` : ''}
        ${paper.conclusion ? `<div class="paper-section"><h4>Conclusion</h4><p>${highlightedConclusion}</p></div>` : ''}
      </div>
      
      ${paper.aiAvailable && highlightedAbstract ? `<h3>Abstract</h3><p class="original-abstract">${highlightedAbstract}</p>` : ''}
      
      ${pdfSource ? `<div class="pdf-preview-section">
        <div class="pdf-header">
          <h3>PDF Preview</h3>
          <button type="button" id="downloadPaperPdf" class="pdf-download-btn">Download PDF</button>
          <button type="button" class="pdf-expand-btn" aria-label="Toggle PDF preview size" onclick="togglePdfSize(this)">
            <svg class="expand-icon" viewBox="0 0 24 24" width="24" height="24">
              <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
            </svg>
            <svg class="collapse-icon" viewBox="0 0 24 24" width="24" height="24" style="display: none;">
              <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>
            </svg>
          </button>
        </div>
        <div id="pdfDownloadStatus" role="status" class="pdf-download-status"></div>
        <div id="pdfDownloadFallback" class="pdf-download-fallback" ${pdfNames.full === pdfNames.download ? 'hidden' : ''}>
          <label for="suggestedPdfName">Full suggested filename</label>
          <input type="text" readonly id="suggestedPdfName">
          <a href="${escapeHtml(pdfSource.url)}" target="_blank" rel="noopener noreferrer">Open PDF</a>
        </div>
        <div class="pdf-container">
          <iframe src="${escapeHtml(pdfSource.url)}" title="Paper PDF preview" width="100%" height="800px" frameborder="0"></iframe>
        </div>
      </div>` : '<p>arXiv PDF unavailable.</p>'}
    </div>
  `;
  
  // Update modal content
  document.getElementById('modalBody').innerHTML = modalContent;
  if (pdfSource) bindPdfDownload(pdfSource, pdfNames);
  document.getElementById('paperLink').href = safeHttpUrl(paper.url);
  pdfLink.href = pdfSource?.url || '#';
  pdfLink.style.display = pdfSource ? '' : 'none';
  document.getElementById('htmlLink').href = safeHttpUrl(paper.url).replace('/abs/', '/html/');
  
  // --- GitHub Button Logic ---
  const githubLink = document.getElementById('githubLink');
  
  if (paper.code_url) {
    githubLink.href = safeHttpUrl(paper.code_url);
    githubLink.style.display = 'flex'; 
    githubLink.title = "View Code on GitHub";
  } else {
    githubLink.style.display = 'none';
  }
  // ---------------------------

  bindChatGPT(paper, pdfSource);
  
  // 更新论文位置信息
  const paperPosition = document.getElementById('paperPosition');
  if (paperPosition && currentFilteredPapers.length > 0) {
    paperPosition.textContent = `${currentPaperIndex + 1} / ${currentFilteredPapers.length}`;
  }
  
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  openPaperId = null;
  const modal = document.getElementById('paperModal');
  const modalBody = document.getElementById('modalBody');
  
  // 重置模态框的滚动位置
  modalBody.scrollTop = 0;
  
  modal.classList.remove('active');
  document.body.style.overflow = '';
}

// 导航到上一篇论文
function navigateToPreviousPaper() {
  if (currentFilteredPapers.length === 0) return;
  
  currentPaperIndex = currentPaperIndex > 0 ? currentPaperIndex - 1 : currentFilteredPapers.length - 1;
  const paper = currentFilteredPapers[currentPaperIndex];
  showPaperDetails(paper, currentPaperIndex + 1);
}

// 导航到下一篇论文
function navigateToNextPaper() {
  if (currentFilteredPapers.length === 0) return;
  
  currentPaperIndex = currentPaperIndex < currentFilteredPapers.length - 1 ? currentPaperIndex + 1 : 0;
  const paper = currentFilteredPapers[currentPaperIndex];
  showPaperDetails(paper, currentPaperIndex + 1);
}

// 显示随机论文
function showRandomPaper() {
  // 检查是否有可用的论文
  if (currentFilteredPapers.length === 0) {
    console.log('No papers available to show random paper');
    return;
  }
  
  // 生成随机索引
  const randomIndex = Math.floor(Math.random() * currentFilteredPapers.length);
  const randomPaper = currentFilteredPapers[randomIndex];
  
  // 更新当前论文索引
  currentPaperIndex = randomIndex;
  
  // 显示随机论文
  showPaperDetails(randomPaper, currentPaperIndex + 1);
  
  // 显示随机论文指示器
  showRandomPaperIndicator();
  
  console.log(`Showing random paper: ${randomIndex + 1}/${currentFilteredPapers.length}`);
}

// 显示随机论文指示器
function showRandomPaperIndicator() {
  // 移除已存在的指示器
  const existingIndicator = document.querySelector('.random-paper-indicator');
  if (existingIndicator) {
    existingIndicator.remove();
  }
  
  // 创建新的指示器
  const indicator = document.createElement('div');
  indicator.className = 'random-paper-indicator';
  indicator.textContent = 'Random Paper';
  
  // 添加到页面
  document.body.appendChild(indicator);
  
  // 3秒后自动移除
  setTimeout(() => {
    if (indicator && indicator.parentNode) {
      indicator.remove();
    }
  }, 3000);
}

function toggleDatePicker() {
  const datePicker = document.getElementById('datePickerModal');
  datePicker.classList.toggle('active');
  
  if (datePicker.classList.contains('active')) {
    document.body.style.overflow = 'hidden';
    
    // 重新初始化日期选择器以确保它反映最新的可用日期
    if (flatpickrInstance) {
      flatpickrInstance.setDate(selectedStartDate === selectedEndDate ? selectedStartDate : [selectedStartDate, selectedEndDate], false);
    }
  } else {
    document.body.style.overflow = '';
  }
}

function toggleView() {
  currentView = currentView === 'grid' ? 'list' : 'grid';
  document.getElementById('paperContainer').classList.toggle('list-view', currentView === 'list');
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric'
  });
}

async function loadPapersByDateRange(startDate, endDate) {
  if (!availableDates.some(date => date >= startDate && date <= endDate)) {
    alert('No available papers in the selected date range.');
    return;
  }
  return loadSelectedPapers(startDate, endDate);
}

// 清除所有激活的关键词
function clearAllKeywords() {
  activeKeywords = [];
  // renderKeywordTags();
  // 重新渲染论文列表，移除关键词匹配的高亮和优先排序
  renderPapers();
}

// 清除所有作者过滤
function clearAllAuthors() {
  activeAuthors = [];
  renderFilterTags();
  // 重新渲染论文列表，移除作者匹配的高亮和优先排序
  renderPapers();
}

// 切换PDF预览器大小
function togglePdfSize(button) {
  const pdfContainer = button.closest('.pdf-preview-section').querySelector('.pdf-container');
  const iframe = pdfContainer.querySelector('iframe');
  const expandIcon = button.querySelector('.expand-icon');
  const collapseIcon = button.querySelector('.collapse-icon');
  
  if (pdfContainer.classList.contains('expanded')) {
    // 恢复正常大小
    pdfContainer.classList.remove('expanded');
    iframe.style.height = '800px';
    expandIcon.style.display = 'block';
    collapseIcon.style.display = 'none';
    
    // 移除遮罩层
    const overlay = document.querySelector('.pdf-overlay');
    if (overlay) {
      overlay.remove();
    }
  } else {
    // 放大显示
    pdfContainer.classList.add('expanded');
    iframe.style.height = '90vh';
    expandIcon.style.display = 'none';
    collapseIcon.style.display = 'block';
    
    // 添加遮罩层
    const overlay = document.createElement('div');
    overlay.className = 'pdf-overlay';
    document.body.appendChild(overlay);
    
    // 点击遮罩层时收起PDF
    overlay.addEventListener('click', () => {
      togglePdfSize(button);
    });
  }
}
