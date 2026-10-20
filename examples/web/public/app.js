const count = document.querySelector('#count');
const visits = document.querySelector('#visits');
async function refreshCount() {
  count.disabled = true;
  try {
    const response = await fetch('/api/visits');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    visits.textContent = `요이~ㅋㅋ 방문 횟수: ${data.visits}`;
  } catch (error) {
    visits.textContent = `요청 실패: ${error.message}`;
  } finally {
    count.disabled = false;
  }
}
count.addEventListener('click', refreshCount);
refreshCount();
