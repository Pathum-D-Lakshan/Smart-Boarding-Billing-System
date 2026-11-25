(() => {
    const roomType = document.getElementById("room_type");
    const rentLabel = document.getElementById("room-rent-label");
    const rentHint = document.getElementById("room-rent-hint");
    if (!roomType || !rentLabel || !rentHint) return;
    function updateRentUnit() {
        const isPrivate = roomType.value === "private";
        rentLabel.textContent = isPrivate ? "Monthly Rent for the Entire Room (LKR)" : "Default Monthly Rent per New Bed (LKR)";
        rentHint.textContent = isPrivate
            ? "Private: one monthly price for the full room. Physical beds are not separately rentable."
            : "Shared: this is the default rent for new beds. Changing this default does not change rents already saved on existing beds.";
    }
    roomType.addEventListener("change", updateRentUnit);
    updateRentUnit();
})();
