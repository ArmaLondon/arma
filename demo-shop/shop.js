function showToast(text) {
  var t = document.getElementById('toast');
  t.textContent = text; t.style.display = 'block';
  clearTimeout(window.__toast); window.__toast = setTimeout(function () { t.style.display = 'none'; }, 2500);
}
function toggleSearch() { showToast('Recherche bientôt disponible'); }
function addToCart() {
  var c = document.querySelector('.cart-count'); c.textContent = parseInt(c.textContent, 10) + 1;
  showToast('Ajouté au panier');
}
function selectSize(el) {
  document.querySelectorAll('.size').forEach(function (s) { s.classList.remove('selected'); });
  el.classList.add('selected');
}
function changeQty(btn, d) {
  var s = btn.parentNode.querySelector('span'); s.textContent = Math.max(1, parseInt(s.textContent, 10) + d);
}
function removeRow(btn) { btn.closest('tr').remove(); }
function pay() {
  var bad = false;
  document.querySelectorAll('#checkout-form input').forEach(function (i) {
    var ok = i.value.trim() !== '' && (i.name !== 'email' || /.+@.+\..+/.test(i.value));
    i.classList.toggle('error', !ok); if (!ok) bad = true;
  });
  if (!bad) showToast('Commande confirmée');
}
