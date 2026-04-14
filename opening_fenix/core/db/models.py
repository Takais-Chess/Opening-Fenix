from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Float, Boolean
from sqlalchemy.orm import declarative_base, relationship
import datetime

# --- REPERTOIRE DATABASE SCHEMA ---
Base = declarative_base()

class Metadata(Base):
    """Stores global settings for this specific repertoire database."""
    __tablename__ = 'metadata'
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)

class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True)
    fen = Column(String, unique=True, nullable=False, index=True)
    
    # Content
    comment = Column(String, nullable=True) 
    variation_1 = Column(String, nullable=True, index=True) 
    variation_2 = Column(String, nullable=True, index=True) 
    variation_3 = Column(String, nullable=True, index=True)
    
    # Cached Inheritance (Denormalization for Speed)
    cached_v1 = Column(String, nullable=True, index=True)
    cached_v2 = Column(String, nullable=True, index=True)
    cached_v3 = Column(String, nullable=True, index=True)
    
    # Analysis
    analysis_depth = Column(Integer, nullable=True)
    good_moves = Column(String, nullable=True) 
    
    # Metrics
    popularity = Column(Integer, default=0) 
    popularity_elo = Column(String, nullable=True) 
    engine_eval = Column(Integer, nullable=True)
    
    # Overhaul & Hole tracking
    last_overhaul_review = Column(DateTime, nullable=True)
    is_hole_exempt = Column(Boolean, default=False)

class Move(Base):
    __tablename__ = 'moves'
    id = Column(Integer, primary_key=True)
    from_position_id = Column(Integer, ForeignKey('positions.id'), nullable=False, index=True)
    to_position_id = Column(Integer, ForeignKey('positions.id'), nullable=False, index=True)
    uci = Column(String(10), nullable=False) 
    san = Column(String(10), nullable=False)
    
    priority_score = Column(Float, default=0.0, index=True)
    nag = Column(Integer, default=0) 

    from_position = relationship("Position", foreign_keys=[from_position_id], backref="outgoing_moves")
    to_position = relationship("Position", foreign_keys=[to_position_id], backref="incoming_moves")
    
    __table_args__ = (UniqueConstraint('from_position_id', 'uci', name='_from_pos_uci_uc'),)

class RepertoireMove(Base):
    """
    Marks a move as being part of the user's active repertoire.
    """
    __tablename__ = 'repertoire_moves'
    id = Column(Integer, primary_key=True)
    move_id = Column(Integer, ForeignKey('moves.id'), nullable=False, index=True)
    level = Column(Integer, default=1, index=True) 
    is_active = Column(Boolean, default=True, index=True)
    
    move = relationship("Move")
    __table_args__ = (UniqueConstraint('move_id', name='_rep_move_uc'),)

class RepertoireLevel(Base):
    """Defines the available levels (e.g. 'Basic', 'Advanced')."""
    __tablename__ = 'repertoire_levels'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    order = Column(Integer, nullable=False, unique=True)
    target_elo = Column(Integer, default=1500)

class LichessData(Base):
    __tablename__ = 'lichess_data'
    id = Column(Integer, primary_key=True)
    fen = Column(String, nullable=False, index=True)
    elo_range = Column(String, nullable=False)
    moves_json = Column(String, nullable=False) 

    __table_args__ = (UniqueConstraint('fen', 'elo_range', name='_fen_elo_uc'),)


# --- USER PROFILE DATABASE SCHEMA ---
UserBase = declarative_base()

class TrainingData(UserBase):
    """
    Stores learning progress for a specific user.
    Linked to repertoire by name and move by FEN+UCI (stable identifiers).
    """
    __tablename__ = 'training_data'
    id = Column(Integer, primary_key=True)
    repertoire_name = Column(String, index=True, nullable=False)
    fen = Column(String, index=True, nullable=False) # The position BEFORE the move
    move_uci = Column(String, nullable=False)
    
    box = Column(Integer, default=0, index=True) 
    next_due = Column(DateTime, default=datetime.datetime.now, index=True)
    streak = Column(Integer, default=0)
    last_review = Column(DateTime, nullable=True)
    
    __table_args__ = (UniqueConstraint('repertoire_name', 'fen', 'move_uci', name='_user_rep_move_uc'),)

class UserRepertoireSettings(UserBase):
    """
    Stores user-specific settings for a repertoire (e.g. active level).
    """
    __tablename__ = 'user_repertoire_settings'
    repertoire_name = Column(String, primary_key=True)
    active_level = Column(Integer, default=1)
    rating = Column(Float, default=800.0)
    last_rating_update = Column(DateTime, nullable=True)
    
    # Caching columns for faster UI updates
    last_new_count = Column(Integer, default=0)
    last_due_count = Column(Integer, default=0)
    last_dist_json = Column(String, nullable=True) # JSON representation of the box distribution
    stats_updated_at = Column(DateTime, nullable=True)
