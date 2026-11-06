// Đồng bộ sáng/tối với Dashboard: cùng khóa localStorage "cutlotdesk.theme", mặc định tối.
(function () {
  var theme = "dark";
  try {
    var saved = window.localStorage.getItem("cutlotdesk.theme") || window.localStorage.getItem("aurumdesk.theme"); // khóa cũ trước khi đổi tên
    if (saved === "light") theme = "light";
  } catch (e) {
    // Bộ nhớ trình duyệt bị chặn: giữ mặc định tối.
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
