(function () {
  function setupLangSwitcher() {
    var select = document.querySelector('.md-header__option .md-select');
    if (!select) return;

    var btn = select.querySelector('.md-header__button');
    var menu = select.querySelector('.md-select__menu, .md-select__list, ul');
    if (!btn || !menu) return;

    var isEn = window.location.pathname.includes('/en/');

    // 1. 按钮只显示目标语言文字
    btn.textContent = isEn ? '中文' : 'English';
    btn.style.fontSize = '14px';
    btn.style.fontWeight = '500';

    // 2. 从下拉菜单里找到目标语言的链接
    var links = menu.querySelectorAll('a');
    var targetUrl = null;
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href') || '';
      // 当前是英文站，目标就是中文链接（不含 /en/）
      // 当前是中文站，目标就是英文链接（含 /en/）
      if (isEn && !href.includes('/en/')) {
        targetUrl = links[i].href;
        break;
      }
      if (!isEn && href.includes('/en/')) {
        targetUrl = links[i].href;
        break;
      }
    }

    // 3. 隐藏下拉菜单
    menu.style.display = 'none';

    // 4. 阻止原下拉菜单弹出，改为直接跳转
    var newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);

    newBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (targetUrl) {
        window.location.href = targetUrl;
      }
    });
  }

  setupLangSwitcher();
  document.addEventListener('DOMContentLoaded', setupLangSwitcher);
})();