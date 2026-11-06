// Đồng bộ sáng/tối với Dashboard: cùng khóa localStorage "aurumdesk.theme", mặc định tối.
(function () {
  var theme = "dark";
  try {
    if (window.localStorage.getItem("aurumdesk.theme") === "light") theme = "light";
  } catch (e) {
    // Bộ nhớ trình duyệt bị chặn: giữ mặc định tối.
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
