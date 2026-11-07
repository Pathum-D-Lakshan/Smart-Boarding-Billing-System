(() => {
    const roomType = document.getElementById("room_type");
    const rentLabel = document.getElementById("room-rent-label");
    const rentHint = document.getElementById("room-rent-hint");
    if (!roomType || !rentLabel || !rentHint) return;
    function updateRentUnit() {
        const isPrivate = roomType.value === "private";
        rentLabel.textContent = isPrivate ? "Monthly Rent per Room (LKR)" : "Monthly Rent per Bed (LKR)";
        rentHint.textContent = isPrivate
            ? "Private: one monthly price for the full room. Physical beds are not separately rentable."
            : "Shared: this is the default rent for new beds. Each registered bed has its own rent.";
    }
    roomType.addEventListener("change", updateRentUnit);
    updateRentUnit();
})();
