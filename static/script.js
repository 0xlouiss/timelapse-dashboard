function updateStatus() {
    fetch('/status')
        .then(response => response.json())
        .then(data => {
            document.getElementById('status-text').innerText = data.status;
            document.getElementById('captured').innerText = data.captured;
            document.getElementById('total').innerText = data.total;
        })
        .catch(err => console.error(err));
}

// Update every 2 seconds
setInterval(updateStatus, 2000);
updateStatus();

